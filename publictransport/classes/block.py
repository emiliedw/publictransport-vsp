from dataclasses import dataclass, field

from .trip import ScheduledTrip
from .charging_event import ChargingEvent


@dataclass
class Block:
    # = A sequence of trips and charging events assigned to one vehicle.
    id: str
    vehicle_id: str
    depot_id: str
    scheduled_trips: list[ScheduledTrip] = field(default_factory=list)
    charging_events: list[ChargingEvent] = field(default_factory=list)

    def add_trip(self, scheduled_trip: ScheduledTrip) -> None:
        self.scheduled_trips.append(scheduled_trip)

    def add_charging_event(self, event: ChargingEvent) -> None:
        self.charging_events.append(event)