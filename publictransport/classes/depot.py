from dataclasses import dataclass, field

from .vehicle_type import VehicleType

@dataclass
class Depot:
    id: str
    name: str
    location_stop_id: str
    fleet_capacity: dict[VehicleType, int] = field(default_factory=dict)

    def available(self, vehicle_type: VehicleType) -> int:
        return self.fleet_capacity.get(vehicle_type, 0)