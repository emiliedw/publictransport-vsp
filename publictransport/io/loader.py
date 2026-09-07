#to read the CSV/XML, builds problemInstance

import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

from ..instance import ProblemInstance
from ..classes.trip import Trip
from ..classes.line import Line
from ..classes.deadhead_trip import DeadheadTrip
from ..classes.depot import Depot
from ..classes.charger import Charger
from ..classes.charger_location_type import ChargerLocationType
from ..classes.vehicle_type import VehicleType
from ..classes.vehicle_type_params import VehicleTypeParams
from ..classes.consumption_model import ConsumptionProfile


def _classify_vehicle_type_name(name: str) -> VehicleType:
    """Map a Polish vehicle-type model name to the broad VehicleType enum.
    No hydrogen models are present in this dataset; add a 'wodor'/'hydrogen'
    substring check here if that changes."""
    lowered = (name or "").lower()
    if "elektryczn" in lowered:
        return VehicleType.ELECTRIC
    if "wodor" in lowered or "hydrogen" in lowered:
        return VehicleType.HYDROGEN
    return VehicleType.CONVENTIONAL


def _estimate_length_m(name: str) -> float:
    """Length isn't in the XML at all - this is a naming-convention guess
    ('przegubowy' = articulated ~18m, otherwise short ~12m), used only to
    fill VehicleTypeParams.length_m, which the solver doesn't currently use
    for any constraint. Replace with real figures if you have them."""
    lowered = (name or "").lower()
    return 18.0 if "przegubow" in lowered else 12.0


def _infer_directions(instance: ProblemInstance) -> None:
    """Infer trip.direction ('0'/'1') from the dominant origin->destination stop-pair per line,
    since the Katowice export has no PatternId/DirectionId field. A trip whose (origin, destination)
    matches neither of its line's two dominant patterns is left as '' (unknown), which safely
    disables the same-direction hard constraint for just that trip rather than misclassifying it.

    Also infers is_circular: per the spec, a circular line is one that "always operates in the
    same direction." If a line has no reverse-pair trips at all, every trip on it shares one
    direction by definition, so it's flagged circular here."""
    trips_by_line: dict[str, list[Trip]] = defaultdict(list)
    for trip in instance.trips.values():
        trips_by_line[trip.line_id].append(trip)

    for line_id, line_trips in trips_by_line.items():
        pair_counts = Counter((t.origin_stop, t.destination_stop) for t in line_trips)
        if not pair_counts:
            continue

        (dir0_origin, dir0_dest), _ = pair_counts.most_common(1)[0]
        dir1_pair = (dir0_dest, dir0_origin)
        has_reverse = pair_counts.get(dir1_pair, 0) > 0

        for trip in line_trips:
            pair = (trip.origin_stop, trip.destination_stop)
            if pair == (dir0_origin, dir0_dest):
                trip.direction = "0"
            elif pair == dir1_pair:
                trip.direction = "1"
            else:
                trip.direction = ""

        line = instance.get_line(line_id)
        if line is not None and not has_reverse:
            line.is_circular = True


def load_from_xml(xml_path: str) -> ProblemInstance:
    """Parse an XML export and build a ProblemInstance from it."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    instance = ProblemInstance()

    # ---- 1. Vehicle type catalogue: guid -> name -> broad VehicleType ----
    vehicle_type_names: dict[str, str] = {}
    for vt_el in root.findall(".//VehicleTypeList/VehicleTypeDto"):
        vt_id = vt_el.findtext("Id")
        if vt_id:
            vehicle_type_names[vt_id] = vt_el.findtext("Name") or ""

    vehicle_type_broad_by_guid: dict[str, VehicleType] = {
        guid: _classify_vehicle_type_name(name) for guid, name in vehicle_type_names.items()
    }

    # ---- 2. Chargers, and a home_id -> stop_id map (depots have no direct
    #         stop-location field of their own; we infer it from whichever
    #         charger location was tagged with that HomeId) ----
    home_location_map: dict[str, str] = {}
    for chg_el in root.findall(".//ChargerLocationList/ChargerLocationDto"):
        location_id = chg_el.findtext("LocationId")
        home_id = chg_el.findtext("HomeId")  # "" for xsi:nil homes (terminus chargers)
        rate_text = chg_el.findtext("EnergyReleaseNorm")

        if location_id:
            charger = Charger(
                id=f"charger_{location_id}",
                location_type=ChargerLocationType.DEPOT if home_id else ChargerLocationType.TERMINUS,
                location_id=location_id,
                charging_rate_kw=float(rate_text) if rate_text else 0.0,
            )
            instance.add_charger(charger)

            if home_id:
                home_location_map[home_id] = location_id

    # ---- 3. Trips (with per-trip vehicle-type compatibility) ----
    line_names: dict[str, str] = {}

    for trip_el in root.findall(".//TripDefDto"):
        line_id = trip_el.findtext("LineId")
        line_names[line_id] = trip_el.findtext("LineName")

        length_text = trip_el.findtext("Length")

        compatible_guids = [g.text for g in trip_el.findall("VehicleTypeIDList/guid") if g.text]
        if compatible_guids:
            vehicle_type_preference = {vt: 0 for vt in VehicleType}
            for guid in compatible_guids:
                broad = vehicle_type_broad_by_guid.get(guid)
                if broad is not None:
                    vehicle_type_preference[broad] = 10
        else:
            # No restriction stated in the data -> every type equally compatible.
            vehicle_type_preference = {vt: 10 for vt in VehicleType}

        trip = Trip(
            id=trip_el.findtext("Id"),
            line_id=line_id,
            start_time=int(trip_el.findtext("StartTime")),
            end_time=int(trip_el.findtext("EndTime")),
            direction="",  # filled in by _infer_directions() below, once all trips are loaded
            origin_stop=trip_el.findtext("StartLocationId"),
            destination_stop=trip_el.findtext("EndLocationId"),
            distance_km=(int(length_text) / 1000 if length_text else 0.0),
            vehicle_type_preference=vehicle_type_preference,
        )
        instance.add_trip(trip)

    for line_id, line_name in line_names.items():
        instance.add_line(Line(id=line_id, name=line_name))
        # NOTE: circularity is inferred below in _infer_directions(), since it isn't
        # present in this XML export directly.

    # ---- 4. Deadheads ----
    for dh_el in root.findall(".//TripTechnicalMatrixDto"):
        origin = dh_el.findtext("StartLocationId")
        destination = dh_el.findtext("EndLocationId")
        duration_text = dh_el.findtext("DriveTime")
        length_text = dh_el.findtext("Length")

        if not all([origin, destination, duration_text, length_text]):
            continue

        deadhead = DeadheadTrip(
            origin_stop=origin,
            destination_stop=destination,
            duration_minutes=int(duration_text) / 60,
            distance_km=int(length_text) / 1000,
        )
        instance.add_deadhead(deadhead)

    # ---- 5. Depots (fleet capacity per home) and VehicleTypeParams
    #         (aggregated across every specific model within a broad type -
    #         see the note at the end of this function) ----
    depot_fleet_totals: dict[str, dict] = {}  # home_id -> {"name":, "fleet_capacity": {}}
    type_totals: dict[VehicleType, dict] = defaultdict(lambda: {
        "count": 0, "capacity_kwh_sum": 0.0, "consumption_sum": 0.0,
        "opcost_sum": 0.0, "length_sum": 0.0,
    })

    for cert_el in root.findall(".//VehicleTypeToHomeToCertificateList/VehicleTypeToHomeToCertificateDto"):
        vt_id = cert_el.findtext("VehicleTypeId")
        vt_name = cert_el.findtext("VehicleTypeName") or vehicle_type_names.get(vt_id, "")
        broad = _classify_vehicle_type_name(vt_name)

        home_id = cert_el.findtext("HomeId")
        home_name = cert_el.findtext("HomeName") or home_id

        count = int(cert_el.findtext("VehicleTypeCount") or 0)
        capacity = float(cert_el.findtext("EnergyStorageCapacity") or 0.0)
        consumption = float(cert_el.findtext("EnergyConsumption_per_km") or 0.0)
        opcost = float(cert_el.findtext("VehicleOperatingCost_per_km") or 0.0)

        if home_id:
            entry = depot_fleet_totals.setdefault(home_id, {"name": home_name, "fleet_capacity": {}})
            entry["fleet_capacity"][broad] = entry["fleet_capacity"].get(broad, 0) + count

        totals = type_totals[broad]
        totals["count"] += count
        totals["capacity_kwh_sum"] += capacity * count
        totals["consumption_sum"] += consumption * count
        totals["opcost_sum"] += opcost * count
        totals["length_sum"] += _estimate_length_m(vt_name) * count

    for home_id, entry in depot_fleet_totals.items():
        location_stop_id = home_location_map.get(home_id)
        if location_stop_id is None:
            print(f"warning: no charger location tagged with HomeId for depot "
                  f"'{entry['name']}' ({home_id}); using the home id itself as a "
                  f"placeholder stop id - deadhead/return-to-depot checks won't "
                  f"resolve correctly for this depot until this is fixed")
            location_stop_id = home_id

        instance.add_depot(Depot(
            id=home_id,
            name=entry["name"],
            location_stop_id=location_stop_id,
            fleet_capacity=entry["fleet_capacity"],
        ))

    ELECTRIC_MIN_SOC_FRACTION = 0.15

    for broad, totals in type_totals.items():
        if totals["count"] == 0:
            continue
        count = totals["count"]
        profile = ConsumptionProfile(
            vehicle_type=broad,
            base_kwh_per_km=totals["consumption_sum"] / count,
        )
        params = VehicleTypeParams(
            vehicle_type=broad,
            length_m=totals["length_sum"] / count,
            operating_cost_per_km=totals["opcost_sum"] / count,
            consumption_profile=profile,
            battery_capacity_kwh=(totals["capacity_kwh_sum"] / count) if totals["capacity_kwh_sum"] > 0 else None,
            min_soc_fraction=(ELECTRIC_MIN_SOC_FRACTION if broad == VehicleType.ELECTRIC else None),
        )
        instance.add_vehicle_type_params(params)
    # ---- 6. Line-change preferences ----
    for lcp_el in root.findall(".//LineChangePreferenceList/LineChangePreferenceDto"):
        source_line = lcp_el.findtext("SourceLineId")
        dest_line = lcp_el.findtext("DestinationLineId")
        pref_text = lcp_el.findtext("Preference")
        if source_line and dest_line and pref_text:
            instance.line_change_preferences[(source_line, dest_line)] = float(pref_text)

    _infer_directions(instance)

    return instance