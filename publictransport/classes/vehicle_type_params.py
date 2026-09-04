from dataclasses import dataclass
from typing import Optional

from .vehicle_type import VehicleType
from .consumption_model import ConsumptionProfile


@dataclass
class VehicleTypeParams:
    vehicle_type: VehicleType
    length_m: float
    operating_cost_per_km: float
    consumption_profile: ConsumptionProfile
    battery_capacity_kwh: Optional[float] = None
    min_soc_fraction: Optional[float] = None
    refuel_time_minutes: Optional[int] = None
    max_virtual_blocks: Optional[int] = None
    min_break_seconds: int = 0
    max_deadhead_seconds: Optional[int] = None
    max_break_seconds: Optional[int] = None