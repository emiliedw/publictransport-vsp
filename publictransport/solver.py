from typing import Optional

from .instance import ProblemInstance
from .solution import Solution
from .classes.block import Block
from .classes.trip import ScheduledTrip
from .classes.vehicle_type import VehicleType


class Solver:

    def __init__(self, instance: ProblemInstance) -> None:
        self.instance = instance

    # ---- vehicle type / compatibility ----

    def _eligible_vehicle_types_by_preference(self, trip) -> list[VehicleType]:
        if not trip.vehicle_type_preference:
            return list(VehicleType)

        scored = [(vt, score) for vt, score in trip.vehicle_type_preference.items() if score != 0]
        if scored:
            return [vt for vt, _ in sorted(scored, key=lambda x: -x[1])]

        return [vt for vt in VehicleType if trip.vehicle_type_preference.get(vt) != 0]

    def _is_compatible(self, trip, vehicle_type: VehicleType) -> bool:
        return trip.vehicle_type_preference.get(vehicle_type) != 0

    def _select_home_depot(self, vehicle_type: VehicleType, origin_stop: str,
                           block_count_by_depot_type: dict[tuple[str, VehicleType], int]):
        candidates = [
            d for d in self.instance.depots.values()
            if block_count_by_depot_type.get((d.id, vehicle_type), 0) < d.available(vehicle_type)
        ]
        if not candidates:
            return None

        def distance_from_origin(depot) -> float:
            if depot.location_stop_id == origin_stop:
                return 0.0
            deadhead = self.instance.get_deadhead(depot.location_stop_id, origin_stop)
            return deadhead.distance_km if deadhead is not None else float("inf")

        return min(candidates, key=distance_from_origin)

    def _electric_feasible(self, block: Block, trip, deadhead_km: float, at_time_seconds: int) -> bool:
        params = self.instance.get_vehicle_type_params(VehicleType.ELECTRIC)
        if params is None:
            return True

        hour = (self.instance.seconds_since_day_start(at_time_seconds) // 3600) % 24
        consumed_so_far = block.energy_consumed_kwh(self.instance, params.consumption_profile)

        deadhead_rate = params.consumption_profile.consumption_kwh_per_km(hour=hour)
        trip_rate = params.consumption_profile.consumption_kwh_per_km(line_id=trip.line_id, hour=hour)
        projected_added = deadhead_km * deadhead_rate + trip.distance_km * trip_rate

        remaining_soc = block.starting_soc_kwh(self.instance, params) - (consumed_so_far + projected_added)
        return remaining_soc >= params.min_soc_floor_kwh()

    # ---- core feasibility + cost ----

    def _find_best_feasible_block(
            self,
            trip,
            candidate_blocks: list[Block],
            trip_shifting: bool,
    ) -> tuple[Optional[Block], Optional[float], int, Optional[ScheduledTrip]]:
        best_block = None
        best_total_cost = None
        best_travel_cost = None
        best_shift = 0
        best_last_scheduled = None
        max_shift_sec = trip.max_shift_minutes * 60 if trip_shifting else 0

        for block in candidate_blocks:
            if not self._is_compatible(trip, block.vehicle_type):
                continue

            last_scheduled = block.scheduled_trips[-1]
            last_trip = self.instance.get_trip(last_scheduled.trip_id)

            if last_trip.destination_stop == trip.origin_stop:
                travel_cost = 0.0
                deadhead_km = 0.0
            else:
                deadhead = self.instance.get_deadhead(last_trip.destination_stop, trip.origin_stop)
                if deadhead is None:
                    continue
                dynamic_cost = self.instance.get_deadhead_duration_seconds(
                    last_trip.destination_stop, trip.origin_stop, trip.start_time
                )
                if dynamic_cost is None:
                    continue
                travel_cost = dynamic_cost
                deadhead_km = deadhead.distance_km

            # hard: no two consecutive same-direction trips on a non-circular line
            if last_trip.direction and trip.direction and last_trip.direction == trip.direction:
                line = self.instance.get_line(trip.line_id)
                last_line = self.instance.get_line(last_trip.line_id)
                is_circular = (line and line.is_circular) or (last_line and last_line.is_circular)
                if not is_circular:
                    continue

            # hard: this specific line-to-line change is forbidden (preference score 0)
            if not self.instance.is_line_change_allowed(last_trip.line_id, trip.line_id):
                continue

            # hard: max line changes per block (lzmax)
            if (trip.line_id != last_trip.line_id
                    and self.instance.max_line_changes_per_block is not None
                    and block.count_line_changes(self.instance) + 1 > self.instance.max_line_changes_per_block):
                continue

            params_for_type = self.instance.get_vehicle_type_params(block.vehicle_type)
            if params_for_type and params_for_type.max_deadhead_distance_km is not None:
                if deadhead_km > params_for_type.max_deadhead_distance_km:
                    continue

            # hard: block must stay able to return to its home depot
            depot = self.instance.get_depot(block.depot_id)
            if depot is not None and trip.destination_stop != depot.location_stop_id:
                if self.instance.get_deadhead(trip.destination_stop, depot.location_stop_id) is None:
                    continue

            gap = trip.start_time - last_scheduled.scheduled_end_time

            tmin, tmax = self.instance.get_break_interval(last_trip, block.vehicle_type)
            effective_min_gap = travel_cost + tmin
            break_duration = gap - travel_cost
            is_split_block_break = break_duration >= self.instance.split_block_min_break_seconds

            if gap >= effective_min_gap:
                required_shift = 0
                if not is_split_block_break and tmax is not None and break_duration > tmax:
                    continue
            else:
                required_shift = effective_min_gap - gap
                if self.instance.timetable_zones is not None:
                    _, max_later_zone = self.instance.timetable_zones.max_shift_without_crossing(trip.start_time)
                else:
                    max_later_zone = max_shift_sec
                later_limit = min(max_shift_sec, max_later_zone)
                if required_shift > later_limit:
                    continue

            # hard: max single-trip break (pbmax), unless it's a legitimate split-block break
            if (not is_split_block_break
                    and self.instance.max_single_trip_break_seconds is not None
                    and break_duration > self.instance.max_single_trip_break_seconds):
                continue

            # hard: a break longer than br_max forces depot return per the configured policy
            if (self.instance.br_max_seconds is not None
                    and break_duration > self.instance.br_max_seconds
                    and not self.instance.is_depot_return_compliant(last_trip.destination_stop, depot)):
                continue

            if block.vehicle_type == VehicleType.ELECTRIC:
                if not self._electric_feasible(block, trip, deadhead_km, trip.start_time):
                    continue

            line_change_penalty = self.instance.get_line_change_penalty(last_trip.line_id, trip.line_id)
            total_cost = travel_cost + self.instance.line_change_penalty_weight_seconds * line_change_penalty

            if best_block is None or total_cost < best_total_cost:
                best_block = block
                best_total_cost = total_cost
                best_travel_cost = travel_cost
                best_shift = required_shift
                best_last_scheduled = last_scheduled

        return best_block, best_travel_cost, best_shift, best_last_scheduled

    def _attach_trip(self, block: Block, trip, travel_cost: float, shift: int, last_scheduled: ScheduledTrip) -> None:
        scheduled_trip = ScheduledTrip(
            trip_id=trip.id,
            scheduled_start_time=trip.start_time + shift,
            scheduled_end_time=trip.end_time + shift,
        )
        block.add_trip(scheduled_trip)
        if block.vehicle_type == VehicleType.ELECTRIC:
            idle_start = last_scheduled.scheduled_end_time + travel_cost
            idle_end = scheduled_trip.scheduled_start_time
            block.try_charge_at_stop(self.instance, trip.origin_stop, idle_start, idle_end)

    # ---- short-block elimination (hard: >= instance.min_block_trips) ----

    def _eliminate_short_blocks(
            self, blocks: list[Block], unassigned_trip_ids: list[str], trip_shifting: bool
    ) -> list[Block]:
        min_trips = self.instance.min_block_trips

        while True:
            short_blocks = [b for b in blocks if len(b.scheduled_trips) < min_trips]
            if not short_blocks:
                return blocks

            dissolved = short_blocks[0]
            blocks.remove(dissolved)

            pending_trip_ids = [
                st.trip_id for st in sorted(dissolved.scheduled_trips, key=lambda st: st.scheduled_start_time)
            ]

            for trip_id in pending_trip_ids:
                trip = self.instance.get_trip(trip_id)
                block, travel_cost, shift, last_scheduled = self._find_best_feasible_block(
                    trip, blocks, trip_shifting
                )
                if block is not None:
                    self._attach_trip(block, trip, travel_cost, shift, last_scheduled)
                else:
                    unassigned_trip_ids.append(trip_id)

    # ---- main loop ----

    def solve(self, trip_shifting: bool = False) -> Solution:
        solution = Solution(instance=self.instance)
        trips = self.instance.get_trips_sorted_by_start_time()

        blocks: list[Block] = []
        next_block_id = 1
        block_count_by_type: dict[VehicleType, int] = {}
        block_count_by_depot_type: dict[tuple[str, VehicleType], int] = {}

        for trip in trips:
            block, travel_cost, shift, last_scheduled = self._find_best_feasible_block(
                trip, blocks, trip_shifting
            )

            if block is not None:
                self._attach_trip(block, trip, travel_cost, shift, last_scheduled)
                continue

            opened = False
            for candidate_type in self._eligible_vehicle_types_by_preference(trip):
                params = self.instance.get_vehicle_type_params(candidate_type)
                max_blocks = params.max_virtual_blocks if params else None
                current_count = block_count_by_type.get(candidate_type, 0)

                if max_blocks is not None and current_count >= max_blocks:
                    continue

                # hard: depot fleet capacity per vehicle type
                depot = self._select_home_depot(candidate_type, trip.origin_stop, block_count_by_depot_type)
                if depot is None:
                    continue

                # hard: block must be able to return to depot even as a single-trip block
                if (trip.destination_stop != depot.location_stop_id
                        and self.instance.get_deadhead(trip.destination_stop, depot.location_stop_id) is None):
                    continue

                new_block = Block(id=f"block_{next_block_id}", depot_id=depot.id, vehicle_type=candidate_type)
                next_block_id += 1
                new_block.add_trip(ScheduledTrip(
                    trip_id=trip.id,
                    scheduled_start_time=trip.start_time,
                    scheduled_end_time=trip.end_time,
                ))
                blocks.append(new_block)
                block_count_by_type[candidate_type] = current_count + 1
                block_count_by_depot_type[(depot.id, candidate_type)] = (
                        block_count_by_depot_type.get((depot.id, candidate_type), 0) + 1
                )
                opened = True
                break

            if not opened:
                solution.unassigned_trip_ids.append(trip.id)

        blocks = self._eliminate_short_blocks(blocks, solution.unassigned_trip_ids, trip_shifting)

        for block in blocks:
            solution.add_block(block)

        solution.validate_trip_assignment_integrity()
        return solution