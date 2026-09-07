from dataclasses import dataclass, field
from typing import Optional

from .vehicle_type import VehicleType


@dataclass
class Line:
    id: str
    name: str
    is_circular: bool = False
    default_min_break_seconds: Optional[int] = None
    default_max_break_seconds: Optional[int] = None