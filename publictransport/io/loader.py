#to read the CSV/XML, builds problemInstance

import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

from ..instance import ProblemInstance
from ..classes.trip import Trip
from ..classes.line import Line
from ..classes.deadhead_trip import DeadheadTrip


def _infer_directions(instance: ProblemInstance) -> None:
    """Infer trip.direction ('0'/'1') from the dominant origin->destination stop-pair per line,
    since the Katowice export has no PatternId/DirectionId field. A trip whose (origin, destination)
    matches neither of its line's two dominant patterns is left as '' (unknown), which safely
    disables the same-direction hard constraint for just that trip rather than misclassifying it.

    Also infers is_circular: per the spec, a circular line is one that "always operates in the
    same direction." If a line has no reverse-pair trips at all, every trip on it shares one
    direction by definition, so it's flagged circular here — otherwise the same-direction hard
    constraint would block chaining any of its trips together, fragmenting blocks unnecessarily."""
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
    line_names: dict[str, str] = {}

    for trip_el in root.findall(".//TripDefDto"):
        line_id = trip_el.findtext("LineId")
        line_names[line_id] = trip_el.findtext("LineName")

        length_text = trip_el.findtext("Length")

        trip = Trip(
            id=trip_el.findtext("Id"),
            line_id=line_id,
            start_time=int(trip_el.findtext("StartTime")),
            end_time=int(trip_el.findtext("EndTime")),
            direction="",  # filled in by _infer_directions() below, once all trips are loaded
            origin_stop=trip_el.findtext("StartLocationId"),
            destination_stop=trip_el.findtext("EndLocationId"),
            distance_km=(int(length_text) / 1000 if length_text else 0.0),
        )
        instance.add_trip(trip)

    # Register a Line record for every line seen. Without this, get_line() always returns None,
    # which silently disables the circular-line exception to the direction constraint, and any
    # other lookup (line-level break overrides, line-change preferences) that expects a real Line.
    for line_id, line_name in line_names.items():
        instance.add_line(Line(id=line_id, name=line_name))
        # NOTE: circularity isn't present in this XML export, so every Line defaults to
        # is_circular=False. If you know which line IDs are circular, set them explicitly, e.g.:
        #   instance.lines[some_line_id].is_circular = True

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

    _infer_directions(instance)

    return instance