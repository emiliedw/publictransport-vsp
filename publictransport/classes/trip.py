from dataclasses import dataclass, field
from typing import Optional
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
    distance_km: float = 0.0   #required for energy consumption calc
    min_break_seconds: Optional[int] = None   # tmin override for the break after this trip
    max_break_seconds: Optional[int] = None  # tmax override
    max_shift_minutes: int = 5
    vehicle_type_preference: dict[VehicleType, int] = field(default_factory=dict)

    def duration(self) -> int:
        return self.end_time - self.start_time


@dataclass
class ScheduledTrip:
    trip_id: str
    scheduled_start_time: int
    scheduled_end_time: int