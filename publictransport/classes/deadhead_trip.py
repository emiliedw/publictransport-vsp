from dataclasses import dataclass


@dataclass
class DeadheadTrip:
    origin_stop: str #where empty run starts
    destination_stop: str #where empty run ends
    duration_minutes: int
    distance_km: float