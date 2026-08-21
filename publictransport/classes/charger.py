from dataclasses import dataclass

from .charger_location_type import ChargerLocationType


@dataclass
class Charger:
    id: str
    location_type: ChargerLocationType
    location_id: str  # depot id or terminus/stop id
    charging_rate_kw: float
    min_charging_minutes: int = 0