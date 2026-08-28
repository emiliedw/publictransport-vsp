from dataclasses import dataclass
from typing import Optional

from .vehicle_type import VehicleType
from .consumption_model import ConsumptionProfile


@dataclass
class VehicleTypeParams:
    vehicle_type: VehicleType
    length_m: float
    operating_cost_per_km: float
    consumption_profile: ConsumptionProfile   # replaces consumption_kwh_per_km
    battery_capacity_kwh: Optional[float] = None
    min_soc_fraction: Optional[float] = None
    refuel_time_minutes: Optional[int] = None