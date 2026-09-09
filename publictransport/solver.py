from .instance import ProblemInstance
from .solution import Solution
from .objective import ObjectiveFunction
from .classes.block import Block
from .classes.trip import ScheduledTrip
from .classes.vehicle_type import VehicleType


class Solver:

    def __init__(self, instance: ProblemInstance, objective: ObjectiveFunction) -> None:
        self.instance = instance
        self.objective = objective

    def _preferred_vehicle_type(self, trip) -> VehicleType:
        if not trip.vehicle_type_preference:
            return VehicleType.CONVENTIONAL
        eligible = {vt: score for vt, score in trip.vehicle_type_preference.items() if score > 0}
        if not eligible:
            return VehicleType.CONVENTIONAL  # no explicit eligible type stated — fall back
        return max(eligible, key=eligible.get)

    def _is_compatible(self, trip, vehicle_type: VehicleType) -> bool:
        """A trip is incompatible with a vehicle type if it's explicitly scored 0."""
        score = trip.vehicle_type_preference.get(vehicle_type)
        return score != 0

    def _select_home_depot(self, vehicle_type: VehicleType):
        for depot in self.instance.depots.values():
            if depot.fleet_capacity.get(vehicle_type, 0) > 0:
                return depot
        return None

    def _evaluate_trip_for_block(self, trip, block, trip_shifting: bool):
        """Check whether `trip` can be appended to `block`, enforcing every constraint
        the solver cares about. Returns (cost, required_shift, last_scheduled) if
        feasible, or None if not. Extracted from the old single-block inner loop so
        it can be reused across the lookahead window."""
        if not self._is_compatible(trip, block.vehicle_type):
            return None

        last_scheduled = block.scheduled_trips[-1]
        last_trip = self.instance.get_trip(last_scheduled.trip_id)

        if last_trip.destination_stop == trip.origin_stop:
            cost = 0
            deadhead_km = 0.0
        else:
            deadhead = self.instance.get_deadhead(last_trip.destination_stop, trip.origin_stop)
            if deadhead is None:
                return None
            dynamic_cost = self.instance.get_deadhead_duration_seconds(
                last_trip.destination_stop, trip.origin_stop, trip.start_time
            )
            if dynamic_cost is None:
                return None
            cost = dynamic_cost
            deadhead_km = deadhead.distance_km

        # constraint 21: no two consecutive same-direction trips on a non-circular line
        if last_trip.direction and trip.direction and last_trip.direction == trip.direction:
            line = self.instance.get_line(trip.line_id)
            last_line = self.instance.get_line(last_trip.line_id)
            is_circular = (line and line.is_circular) or (last_line and last_line.is_circular)
            if not is_circular:
                return None

        # constraint 27: this specific line-to-line change is forbidden (score 0)
        if not self.instance.is_line_change_allowed(last_trip.line_id, trip.line_id):
            return None

        preferred_type = block.vehicle_type
        params_for_type = self.instance.get_vehicle_type_params(preferred_type)

        if params_for_type and params_for_type.max_deadhead_distance_km is not None:
            if deadhead_km > params_for_type.max_deadhead_distance_km:
                return None

        gap = trip.start_time - last_scheduled.scheduled_end_time

        tmin, tmax = self.instance.get_break_interval(last_trip, preferred_type)
        effective_min_gap = cost + tmin

        break_duration = gap - cost
        is_split_block_break = break_duration >= self.instance.split_block_min_break_seconds

        if not is_split_block_break and tmax is not None and break_duration > tmax:
            return None

        max_shift_sec = trip.max_shift_minutes * 60 if trip_shifting else 0

        if self.instance.timetable_zones is not None:
            _, max_later_zone = self.instance.timetable_zones.max_shift_without_crossing(trip.start_time)
        else:
            max_later_zone = max_shift_sec

        if gap >= effective_min_gap:
            # Gap is already sufficient without any shift - leave the trip at its
            # original time. Shifting here bought no feasibility, since deadhead
            # cost doesn't change with shift; it only added unnecessary schedule
            # disruption.
            required_shift = 0
        else:
            required_shift = effective_min_gap - gap
            later_limit = min(max_shift_sec, max_later_zone)
            if required_shift > later_limit:
                return None

        if block.vehicle_type == VehicleType.ELECTRIC:
            params = self.instance.get_vehicle_type_params(VehicleType.ELECTRIC)
            hour = (self.instance.seconds_since_day_start(trip.start_time) // 3600) % 24

            consumed_so_far = block.energy_consumed_kwh(self.instance, params.consumption_profile)

            deadhead_rate = params.consumption_profile.consumption_kwh_per_km(hour=hour)
            trip_rate = params.consumption_profile.consumption_kwh_per_km(line_id=trip.line_id, hour=hour)
            projected_added = deadhead_km * deadhead_rate + trip.distance_km * trip_rate

            projected_consumed = consumed_so_far + projected_added
            remaining_soc = block.starting_soc_kwh(self.instance, params) - projected_consumed

            min_soc_kwh = params.min_soc_floor_kwh()
            if remaining_soc < min_soc_kwh:
                return None

        return cost, required_shift, last_scheduled

    def solve(self, trip_shifting: bool = False, lookahead_window: int = 5) -> Solution:
        """Process trips in non-overlapping batches of `lookahead_window` trips. Within
        each batch, every (trip, block) pair is evaluated once, and the cheapest
        non-conflicting matches are committed together - a real reservation, not a
        hypothetical one recomputed and possibly discarded later. This avoids the
        earlier sliding-window design, where only the first trip's decision was
        committed and every other "win" in the window was thrown away and
        re-evaluated independently, which meant larger windows just added phantom
        competition without any compensating benefit (more forced new/short blocks).
        Set lookahead_window=1 to reproduce plain one-trip-at-a-time greedy."""

        solution = Solution(instance=self.instance)

        trips = self.instance.get_trips_sorted_by_start_time()
        n = len(trips)
        window_size = max(1, lookahead_window)

        blocks: list[Block] = []
        next_block_id = 1
        block_count_by_type: dict[VehicleType, int] = {}

        idx = 0
        while idx < n:
            window = trips[idx: idx + window_size]

            # ---- evaluate every (trip, block) pair in this batch, against
            #      block state as it stood BEFORE this batch (no staleness,
            #      since each block can be claimed by at most one trip below) ----
            candidates = []
            for w_trip in window:
                preferred_type = self._preferred_vehicle_type(w_trip)
                for block in blocks:
                    if block.vehicle_type != preferred_type:
                        continue
                    result = self._evaluate_trip_for_block(w_trip, block, trip_shifting)
                    if result is not None:
                        cost, shift, last_scheduled = result
                        candidates.append((cost, w_trip, block, shift, last_scheduled))

            candidates.sort(key=lambda c: (c[0], c[4].scheduled_end_time))

            claimed_trip_ids = set()
            claimed_block_ids = set()
            assignment = {}  # trip.id -> (block, shift, last_scheduled, cost)
            for cost, w_trip, block, shift, last_scheduled in candidates:
                if w_trip.id in claimed_trip_ids or id(block) in claimed_block_ids:
                    continue
                assignment[w_trip.id] = (block, shift, last_scheduled, cost)
                claimed_trip_ids.add(w_trip.id)
                claimed_block_ids.add(id(block))

            # ---- commit every trip in this batch, in time order, so new
            #      blocks open in chronological order and gap/shift math stays sound ----
            for w_trip in window:
                match = assignment.get(w_trip.id)
                if match is not None:
                    block, shift, last_scheduled, cost = match
                    scheduled_trip = ScheduledTrip(
                        trip_id=w_trip.id,
                        scheduled_start_time=w_trip.start_time + shift,
                        scheduled_end_time=w_trip.end_time + shift,
                    )
                    block.add_trip(scheduled_trip)
                    if block.vehicle_type == VehicleType.ELECTRIC:
                        idle_start = last_scheduled.scheduled_end_time + cost
                        idle_end = scheduled_trip.scheduled_start_time
                        block.try_charge_at_stop(self.instance, w_trip.origin_stop, idle_start, idle_end)
                else:
                    scheduled_trip = ScheduledTrip(
                        trip_id=w_trip.id,
                        scheduled_start_time=w_trip.start_time,
                        scheduled_end_time=w_trip.end_time,
                    )
                    preferred_type = self._preferred_vehicle_type(w_trip)
                    params = self.instance.get_vehicle_type_params(preferred_type)
                    max_blocks = params.max_virtual_blocks if params else None
                    current_count = block_count_by_type.get(preferred_type, 0)

                    if max_blocks is not None and current_count >= max_blocks:
                        solution.unassigned_trip_ids.append(w_trip.id)
                        continue

                    depot = self._select_home_depot(preferred_type)
                    if depot is None:
                        solution.unassigned_trip_ids.append(w_trip.id)
                        continue

                    new_block = Block(id=f"block_{next_block_id}", depot_id=depot.id, vehicle_type=preferred_type)
                    next_block_id += 1
                    new_block.add_trip(scheduled_trip)
                    blocks.append(new_block)
                    block_count_by_type[preferred_type] = current_count + 1

            idx += window_size

        for block in blocks:
            solution.add_block(block)
            if not block.can_return_to_depot(self.instance):
                print(f"warning: {block.id} cannot return to its home depot ({block.depot_id})")
            if not block.meets_minimum_requirements(self.instance):
                print(f"warning: {block.id} does not meet minimum trips/duration requirements "
                      f"({len(block.scheduled_trips)} trips, {block.duration_seconds()/60:.1f} min)")

        solution.validate_trip_assignment_integrity()
        return solution