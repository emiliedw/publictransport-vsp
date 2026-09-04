from dataclasses import dataclass

from .charger_location_type import ChargerLocationType


@dataclass
class Charger:
    id: str
    location_type: ChargerLocationType
    location_id: str
    charging_rate_kw: float
    min_charging_minutes: int = 0
    available_from_seconds: int = 0        # NEW — seconds since operating-day start
    available_to_seconds: int = 86400      # NEW — seconds since operating-day start

    def is_available(self, window_start: int, window_end: int, day_start_offset: int) -> bool:
        norm_start = (window_start - day_start_offset) % 86400
        norm_end = (window_end - day_start_offset) % 86400
        if norm_end < norm_start:
            norm_end += 86400  # window crosses the day boundary
        return norm_start >= self.available_from_seconds and norm_end <= self.available_to_seconds