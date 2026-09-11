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

    def _evaluate_trip_pair(self, prev_trip, trip, prev_end_time, vehicle_type, trip_shifting):
        """Check whether `trip` can feasibly follow `prev_trip`, given the predecessor's
        effective end time `prev_end_time`. Passing prev_trip.end_time gives a pairwise,
        chain-history-independent check (used by the exact bipartite solver below);
        passing a block's actual scheduled_end_time gives the chain-cumulative check
        the windowed electric path needs. Returns (cost, required_shift, deadhead_km)
        or None if infeasible."""
        if not self._is_compatible(trip, vehicle_type):
            return None

        if prev_trip.destination_stop == trip.origin_stop:
            cost = 0
            deadhead_km = 0.0
        else:
            deadhead = self.instance.get_deadhead(prev_trip.destination_stop, trip.origin_stop)
            if deadhead is None:
                return None
            dynamic_cost = self.instance.get_deadhead_duration_seconds(
                prev_trip.destination_stop, trip.origin_stop, trip.start_time
            )
            if dynamic_cost is None:
                return None
            cost = dynamic_cost
            deadhead_km = deadhead.distance_km

        # constraint 21: no two consecutive same-direction trips on a non-circular line
        if prev_trip.direction and trip.direction and prev_trip.direction == trip.direction:
            line = self.instance.get_line(trip.line_id)
            prev_line = self.instance.get_line(prev_trip.line_id)
            is_circular = (line and line.is_circular) or (prev_line and prev_line.is_circular)
            if not is_circular:
                return None

        # constraint 27: this specific line-to-line change is forbidden (score 0)
        if not self.instance.is_line_change_allowed(prev_trip.line_id, trip.line_id):
            return None

        params_for_type = self.instance.get_vehicle_type_params(vehicle_type)
        if params_for_type and params_for_type.max_deadhead_distance_km is not None:
            if deadhead_km > params_for_type.max_deadhead_distance_km:
                return None

        gap = trip.start_time - prev_end_time

        tmin, tmax = self.instance.get_break_interval(prev_trip, vehicle_type)
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
            required_shift = 0
        else:
            required_shift = effective_min_gap - gap
            later_limit = min(max_shift_sec, max_later_zone)
            if required_shift > later_limit:
                return None

        return cost, required_shift, deadhead_km

    def _evaluate_trip_for_block(self, trip, block, trip_shifting):
        """Chain-cumulative feasibility check for the windowed (electric) path - wraps
        _evaluate_trip_pair using the block's actual (possibly already-shifted)
        last scheduled end time, then layers the electric SoC check on top."""
        last_scheduled = block.scheduled_trips[-1]
        last_trip = self.instance.get_trip(last_scheduled.trip_id)

        result = self._evaluate_trip_pair(
            last_trip, trip, last_scheduled.scheduled_end_time, block.vehicle_type, trip_shifting
        )
        if result is None:
            return None
        cost, required_shift, deadhead_km = result

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



    def _solve_bipartite(self, trips_group, vehicle_type, trip_shifting):
        ordered = sorted(trips_group, key=lambda t: t.start_time)
        chains = self._match_chains(ordered, vehicle_type, trip_shifting)

        blocks: list[Block] = []
        for chain in chains:
            blocks.extend(self._walk_chain(chain, vehicle_type, trip_shifting))
        return blocks

    def _walk_chain(self, chain, vehicle_type, trip_shifting):
        """Walk one matched chain, splitting into a new Block wherever the
        chain-aware feasibility check fails."""
        blocks = []
        block = None

        for trip in chain:
            if block is not None:
                result = self._evaluate_trip_for_block(trip, block, trip_shifting)
            else:
                result = None  # force fresh-block branch below

            if block is None or result is None:
                if block is not None:
                    blocks.append(block)
                block = Block(id="", depot_id="", vehicle_type=vehicle_type)
                block.add_trip(ScheduledTrip(
                    trip_id=trip.id,
                    scheduled_start_time=trip.start_time,
                    scheduled_end_time=trip.end_time,
                ))
                continue

            cost, shift, last_scheduled = result
            scheduled_trip = ScheduledTrip(
                trip_id=trip.id,
                scheduled_start_time=trip.start_time + shift,
                scheduled_end_time=trip.end_time + shift,
            )
            block.add_trip(scheduled_trip)
            if vehicle_type == VehicleType.ELECTRIC:
                idle_start = last_scheduled.scheduled_end_time + cost
                idle_end = scheduled_trip.scheduled_start_time
                block.try_charge_at_stop(self.instance, trip.origin_stop, idle_start, idle_end)

        if block is not None:
            blocks.append(block)
        return blocks

    def _match_chains(self, trips_group, vehicle_type, trip_shifting):
        """Run the bipartite matching only (no Block construction, no repair) and
        return the resulting chains as lists of Trip objects in chain order.
        Chain-start order is sorted by trip start time for determinism."""
        import scipy.sparse as sp
        from scipy.sparse.csgraph import min_weight_full_bipartite_matching

        n = len(trips_group)
        if n == 0:
            return []

        DUMMY_COST = 1e6
        FALLBACK_COST = 1e6
        COST_EPSILON = 1e-6

        rows, cols, data = [], [], []
        for i, prev_trip in enumerate(trips_group):
            for j, trip in enumerate(trips_group):
                if i == j:
                    continue
                if trip.start_time < prev_trip.end_time:
                    continue
                result = self._evaluate_trip_pair(
                    prev_trip, trip, prev_trip.end_time, vehicle_type, trip_shifting
                )
                if result is not None:
                    cost, _shift, _deadhead_km = result
                    line_penalty = self.instance.get_line_change_penalty(prev_trip.line_id, trip.line_id)
                    edge_weight = cost + line_penalty * self.instance.line_change_penalty_weight_seconds
                    rows.append(i)
                    cols.append(j)
                    data.append(edge_weight + COST_EPSILON)
        for i in range(n):
            rows.append(i); cols.append(n + i); data.append(DUMMY_COST)
            rows.append(n + i); cols.append(i); data.append(DUMMY_COST)

        for a in range(n):
            base = n + a
            rows.extend([base] * n)
            cols.extend(range(n, 2 * n))
            data.extend([FALLBACK_COST] * n)

        size = 2 * n
        matrix = sp.csr_matrix((data, (rows, cols)), shape=(size, size))
        row_ind, col_ind = min_weight_full_bipartite_matching(matrix)

        successor = {int(r): int(c) for r, c in zip(row_ind, col_ind) if r < n and c < n}
        has_predecessor = set(successor.values())
        chain_starts = sorted(
            (i for i in range(n) if i not in has_predecessor),
            key=lambda i: trips_group[i].start_time,
        )

        chains = []
        for start in chain_starts:
            chain_indices = []
            idx = start
            while idx is not None:
                chain_indices.append(idx)
                idx = successor.get(idx)
            chains.append([trips_group[i] for i in chain_indices])

        return chains

    def solve(self, trip_shifting: bool = False) -> Solution:
        solution = Solution(instance=self.instance)
        next_block_id = 1
        block_count_by_type: dict[VehicleType, int] = {}

        trips_by_type: dict[VehicleType, list] = {}
        for trip in self.instance.get_trips_sorted_by_start_time():
            preferred_type = self._preferred_vehicle_type(trip)
            trips_by_type.setdefault(preferred_type, []).append(trip)

        all_blocks: list[Block] = []

        for vehicle_type, trips_group in trips_by_type.items():
            blocks = self._solve_bipartite(trips_group, vehicle_type, trip_shifting)

            params = self.instance.get_vehicle_type_params(vehicle_type)
            max_blocks = params.max_virtual_blocks if params else None

            for block in blocks:
                current_count = block_count_by_type.get(vehicle_type, 0)

                if max_blocks is not None and current_count >= max_blocks:
                    for scheduled in block.scheduled_trips:
                        solution.unassigned_trip_ids.append(scheduled.trip_id)
                    continue

                depot = self._select_home_depot(vehicle_type)
                if depot is None:
                    for scheduled in block.scheduled_trips:
                        solution.unassigned_trip_ids.append(scheduled.trip_id)
                    continue

                block.id = f"block_{next_block_id}"
                block.depot_id = depot.id
                next_block_id += 1
                all_blocks.append(block)
                block_count_by_type[vehicle_type] = current_count + 1

        for block in all_blocks:
            solution.add_block(block)
            if not block.can_return_to_depot(self.instance):
                print(f"warning: {block.id} cannot return to its home depot ({block.depot_id})")
            if not block.meets_minimum_requirements(self.instance):
                print(f"warning: {block.id} does not meet minimum trips/duration requirements "
                      f"({len(block.scheduled_trips)} trips, {block.duration_seconds()/60:.1f} min)")

        solution.validate_trip_assignment_integrity()
        return solution


