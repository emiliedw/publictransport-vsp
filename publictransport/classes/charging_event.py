from dataclasses import dataclass


@dataclass
class ChargingEvent:
    vehicle_id: str
    charger_id: str
    start_time: int
    end_time: int
    energy_added_kwh: float = 0.0