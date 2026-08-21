from dataclasses import dataclass, field

from .vehicle_type import VehicleType

@dataclass
class Trip:
    id: str
    line_id: str
    start_time: int
    end_time: int
    direction: str
    origin_stop: str
    destination_stop: str

    max_shift_minutes: int=5
    vehicle_type_preference: dict[VehicleType, int]= field(default_factory=dict) #this calls dict() fresh for each new isntance

    def duration(self)->int:
        return self.end_time-self.start_time


@dataclass
class ScheduledTrip:
    trip_id: str
    scheduled_start_time: int
    scheduled_end_time: int