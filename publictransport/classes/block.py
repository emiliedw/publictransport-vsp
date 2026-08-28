from dataclasses import dataclass, field

from .trip import ScheduledTrip
from .charging_event import ChargingEvent


class Block:
    def __init__(self, id: str, depot_id: str, vehicle_id: str = ""):
        self.id = id
        self.depot_id = depot_id
        self.vehicle_id = vehicle_id
        self.scheduled_trips = []
        self.charging_events = []

    def add_trip(self, scheduled_trip) -> None:
        self.scheduled_trips.append(scheduled_trip)

    def add_charging_event(self, event) -> None:
        self.charging_events.append(event)

    def can_return_to_depot(self, instance) -> bool:
        """Hard constraint 4: a block must end at the same depot it started from."""
        if not self.scheduled_trips:
            return True  # nothing scheduled yet, nothing to check

        depot = instance.get_depot(self.depot_id)
        if depot is None:
            return False

        last_scheduled = self.scheduled_trips[-1]
        last_trip = instance.get_trip(last_scheduled.trip_id)

        if last_trip.destination_stop == depot.location_stop_id:
            return True  # already sitting at the depot

        deadhead = instance.get_deadhead(last_trip.destination_stop, depot.location_stop_id)
        return deadhead is not None