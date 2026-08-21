#to read the CSV/XML, builds problemInstance

import xml.etree.ElementTree as ET

from ..instance import ProblemInstance
from ..classes.trip import Trip
from ..classes.deadhead_trip import DeadheadTrip


def load_from_xml(xml_path: str) -> ProblemInstance:
    """Parse an XML export and build a ProblemInstance from it."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    instance = ProblemInstance()

    for trip_el in root.findall(".//TripDefDto"):
        trip = Trip(
            id=trip_el.findtext("Id"),
            line_id=trip_el.findtext("LineId"),
            start_time=int(trip_el.findtext("StartTime")),
            end_time=int(trip_el.findtext("EndTime")),
            direction="",  #not present in the file, distract from other info start/stop
            origin_stop=trip_el.findtext("StartLocationId"),
            destination_stop=trip_el.findtext("EndLocationId"),
        )
        instance.add_trip(trip)

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

    return instance