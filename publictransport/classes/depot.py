from dataclasses import dataclass, field

from .vehicle_type import VehicleType

@dataclass
class Depot:
    id: str
    name: str
    capacity: dict[VehicleType, int] #2.3.10: each depot has specified number of vehicles of each type available


    def available(self, vehicle_type: VehicleType)->int:
        return self.capacity.get(vehicle_type, 0)