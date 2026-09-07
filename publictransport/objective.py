from dataclasses import dataclass

from .solution import Solution
from .classes.vehicle_type import VehicleType


@dataclass
class ObjectiveWeights:
    num_blocks: float = 1.0
    line_change_penalty: float = 1.0
    num_unassigned_trips: float = 0.0
    num_short_blocks: float = 0.0
    num_single_trip_blocks: float = 0.0
    vehicle_preference_mismatch: float = 0.0
    trip_shift_amount: float = 0.0
    statutory_break_shortfall: float = 0.0
    overcharging_penalty: float = 0.0
    excess_line_changes: float = 0.0
    single_trip_break_excess: float = 0.0
    long_break_depot_violation: float = 0.0
class ObjectiveFunction:
    def __init__(self, weights: ObjectiveWeights) -> None:
        self.weights = weights

    @staticmethod
    def _normalize(value: float, scale: float) -> float:
        """Map a non-negative raw value to [0, 1] using a natural upper-bound scale."""
        if scale <= 0:
            return 0.0
        return min(1.0, value / scale)

    def evaluate(self, solution: Solution) -> float:
        instance = solution.instance
        blocks = list(solution.blocks.values())
        num_trips = len(instance.trips)
        num_blocks = len(blocks)

        score = 0.0

        # ---- Basic components ----
        score += self.weights.num_blocks * self._normalize(num_blocks, num_trips)

        total_line_change_penalty = sum(b.line_change_penalty(instance) for b in blocks)
        score += self.weights.line_change_penalty * self._normalize(total_line_change_penalty, num_trips * 10)

        # ---- Alternative components ----
        if self.weights.num_unassigned_trips > 0:
            num_unassigned = len(solution.unassigned_trip_ids)
            score += self.weights.num_unassigned_trips * self._normalize(num_unassigned, num_trips)

        if self.weights.num_short_blocks > 0:
            num_short = sum(1 for b in blocks if b.is_short_block(instance))
            score += self.weights.num_short_blocks * self._normalize(num_short, num_blocks)

        if self.weights.num_single_trip_blocks > 0:
            num_single = sum(1 for b in blocks if b.is_single_trip_block())
            score += self.weights.num_single_trip_blocks * self._normalize(num_single, num_blocks)

        if self.weights.vehicle_preference_mismatch > 0:
            total_pref_penalty = sum(b.vehicle_preference_penalty(instance) for b in blocks)
            score += self.weights.vehicle_preference_mismatch * self._normalize(total_pref_penalty, num_trips)

        if self.weights.trip_shift_amount > 0:
            total_shift = sum(b.total_shift_seconds(instance) for b in blocks)
            total_max_shift = sum(b.total_max_shift_seconds(instance) for b in blocks)
            score += self.weights.trip_shift_amount * self._normalize(total_shift, total_max_shift)

        if self.weights.statutory_break_shortfall > 0:
            total_shortfall = sum(b.statutory_break_penalty(instance) for b in blocks)
            max_possible_shortfall = num_blocks * max((needed for _, needed in instance.duty_break_thresholds), default=1)
            score += self.weights.statutory_break_shortfall * self._normalize(total_shortfall, max_possible_shortfall)

        if self.weights.overcharging_penalty > 0:
            total_overcharge = 0.0
            total_battery_capacity = 0.0
            for b in blocks:
                if b.vehicle_type != VehicleType.ELECTRIC:
                    continue
                params = instance.get_vehicle_type_params(b.vehicle_type)
                if params is None:
                    continue
                total_overcharge += b.overcharging_penalty_kwh(instance, params)
                if params.battery_capacity_kwh is not None:
                    total_battery_capacity += params.battery_capacity_kwh

            score += self.weights.overcharging_penalty * self._normalize(total_overcharge, total_battery_capacity or 1.0)

        if self.weights.excess_line_changes > 0:
            total_excess = sum(b.line_change_count_excess(instance) for b in blocks)
            max_possible_excess = sum(len(b.scheduled_trips) for b in blocks)  # worst case: every trip is a line change
            score += self.weights.excess_line_changes * self._normalize(total_excess, max_possible_excess or 1)

        if self.weights.single_trip_break_excess > 0:
            total_excess_seconds = sum(b.single_trip_break_excess_seconds(instance) for b in blocks)
            total_possible_breaks = sum(max(0, len(b.scheduled_trips) - 1) for b in blocks)
            max_scale = total_possible_breaks * (instance.max_single_trip_break_seconds or 1)
            score += self.weights.single_trip_break_excess * self._normalize(total_excess_seconds, max_scale or 1)

        if self.weights.long_break_depot_violation > 0:
            total_violation = sum(b.long_break_depot_violation_seconds(instance) for b in blocks)
            total_possible_breaks = sum(max(0, len(b.scheduled_trips) - 1) for b in blocks)
            max_scale = total_possible_breaks * (instance.br_max_seconds or 1)
            score += self.weights.long_break_depot_violation * self._normalize(total_violation, max_scale or 1)

        return score

    def environmental_kpi(self, solution: Solution) -> float:
        """Auxiliary environmental KPI (NOT part of the weighted objective):
        total energy consumed by electric blocks, in kWh."""
        instance = solution.instance
        total_kwh = 0.0
        for block in solution.blocks.values():
            if block.vehicle_type != VehicleType.ELECTRIC:
                continue
            params = instance.get_vehicle_type_params(block.vehicle_type)
            if params is None:
                continue
            total_kwh += block.energy_consumed_kwh(instance, params.consumption_profile)
        return total_kwh
