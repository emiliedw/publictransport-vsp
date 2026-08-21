from dataclasses import dataclass

@dataclass
class Line:
    id: str
    name: str
    is_circular: bool= False #circular line operates in same direction always