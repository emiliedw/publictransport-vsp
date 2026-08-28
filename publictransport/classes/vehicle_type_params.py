from dataclasses import dataclass
from typing import Optional

from .vehicle_type import VehicleType


@dataclass
class VehicleTypeParams:
    vehicle_type: VehicleType
    length_m: float
    operating_cost_per_km: float

    # Conventional / hydrogen: range is assumed sufficient for any block, so no range field is needed for them here.
    # Electric only:
    battery_capacity_kwh: Optional[float] = None       # total usable capacity
    min_soc_fraction: Optional[float] = None           # safety buffer: never go belof
    consumption_kwh_per_km: Optional[float] = None      #to translate distance into SoC drop

    # Conventional / hydrogen: refueling time at depot before block start
    refuel_time_minutes: Optional[int] = None
    # Electric: charging is scheduled separately (next constraint), not a fixed pre-block refuel