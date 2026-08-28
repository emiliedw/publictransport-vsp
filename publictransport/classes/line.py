from dataclasses import dataclass, field

from .vehicle_type import VehicleType


@dataclass
class Line:
    id: str
    name: str
    is_circular: bool = False