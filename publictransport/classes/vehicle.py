from dataclasses import dataclass
from typing import Optional
from .vehicle_type import VehicleType  # if you split the enum out too

@dataclass
class Vehicle:
    id: str
    vehicle_type: VehicleType
    home_depot_id: str

    def is_electric(self) -> bool:
        return self.vehicle_type == VehicleType.ELECTRIC