from dataclasses import dataclass, field
from typing import Optional

from .vehicle_type import VehicleType


@dataclass
class ConsumptionProfile:
    """Energy consumption parameters for one vehicle type, with optional context-dependent coefficients."""
    vehicle_type: VehicleType
    base_kwh_per_km: float  # mandatory baseline

    # Optional multiplicative coefficients — default to 1.0 (no effect) when absent
    line_coefficients: dict[str, float] = field(default_factory=dict)          # line_id -> multiplier
    time_of_day_coefficients: dict[int, float] = field(default_factory=dict)   # hour (0-23) -> multiplier
    season_coefficients: dict[str, float] = field(default_factory=dict)        # e.g. "winter" -> multiplier
    temperature_coefficient_per_degree: Optional[float] = None                 # multiplier shift per °C from reference
    reference_temperature_c: float = 20.0
    hvac_active_coefficient: Optional[float] = None                            # multiplier when AC/heating is on

    def consumption_kwh_per_km(
            self,
            line_id: Optional[str] = None,
            hour: Optional[int] = None,
            season: Optional[str] = None,
            ambient_temperature_c: Optional[float] = None,
            hvac_active: bool = False,
    ) -> float:
        rate = self.base_kwh_per_km

        if line_id is not None:
            rate *= self.line_coefficients.get(line_id, 1.0)

        if hour is not None:
            rate *= self.time_of_day_coefficients.get(hour, 1.0)

        if season is not None:
            rate *= self.season_coefficients.get(season, 1.0)

        if ambient_temperature_c is not None and self.temperature_coefficient_per_degree is not None:
            delta = ambient_temperature_c - self.reference_temperature_c
            rate *= (1.0 + self.temperature_coefficient_per_degree * delta)

        if hvac_active and self.hvac_active_coefficient is not None:
            rate *= self.hvac_active_coefficient

        return rate