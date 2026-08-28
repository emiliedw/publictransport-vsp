from .instance import ProblemInstance
from .solution import Solution
from .objective import ObjectiveFunction
from .classes.block import Block
from .classes.trip import ScheduledTrip
from .classes.vehicle_type import VehicleType


class Solver:

    ## input: list op trips, deadhead table
    ## output: list of blocks

    def __init__(self, instance: ProblemInstance, objective: ObjectiveFunction) -> None:
        self.instance = instance
        self.objective = objective

    def _preferred_vehicle_type(self, trip) -> VehicleType:
        if not trip.vehicle_type_preference:
            return VehicleType.CONVENTIONAL
        return max(trip.vehicle_type_preference, key=trip.vehicle_type_preference.get)

    def _select_home_depot(self, vehicle_type: VehicleType):
        """Pick a depot that actually has capacity for this vehicle type, if any."""
        for depot in self.instance.depots.values():
            if depot.fleet_capacity.get(vehicle_type, 0) > 0:
                return depot
        return None


    def solve(self, trip_shifting: bool = False) -> Solution:

        solution = Solution(instance=self.instance)

        trips = self.instance.get_trips_sorted_by_start_time()

        blocks: list[Block] = []
        next_block_id = 1
        block_count_by_type: dict[VehicleType, int] = {}

        for trip in trips:
            best_block = None
            best_cost = None
            best_shift = 0
            best_last_scheduled = None
            max_shift_sec = trip.max_shift_minutes * 60 if trip_shifting else 0

            preferred_type = self._preferred_vehicle_type(trip)

            for block in blocks:
                if block.vehicle_type != preferred_type:
                    continue
                last_scheduled = block.scheduled_trips[-1]
                last_trip = self.instance.get_trip(last_scheduled.trip_id)

                if last_trip.destination_stop == trip.origin_stop:
                    cost = 0
                    deadhead_km = 0.0
                else:
                    deadhead = self.instance.get_deadhead(
                        last_trip.destination_stop, trip.origin_stop
                    )
                    if deadhead is None:
                        continue
                    cost = deadhead.duration_minutes * 60
                    deadhead_km = deadhead.distance_km

                gap = trip.start_time - last_scheduled.scheduled_end_time

                if gap >= cost:
                    slack = gap - cost
                    earlier_shift = min(slack, max_shift_sec)
                    required_shift = -earlier_shift if earlier_shift > 0 else 0
                else:
                    required_shift = cost - gap
                    if required_shift > max_shift_sec:
                        continue

                if block.vehicle_type == VehicleType.ELECTRIC:
                    params = self.instance.get_vehicle_type_params(VehicleType.ELECTRIC)
                    hour = (trip.start_time // 3600) % 24

                    consumed_so_far = block.energy_consumed_kwh(self.instance, params.consumption_profile)

                    deadhead_rate = params.consumption_profile.consumption_kwh_per_km(hour=hour)
                    trip_rate = params.consumption_profile.consumption_kwh_per_km(line_id=trip.line_id, hour=hour)
                    projected_added = deadhead_km * deadhead_rate + trip.distance_km * trip_rate

                    projected_consumed = consumed_so_far + projected_added
                    remaining_soc = params.battery_capacity_kwh - projected_consumed
                    min_soc_kwh = params.min_soc_fraction * params.battery_capacity_kwh
                    if remaining_soc < min_soc_kwh:
                        continue  # not enough range left, this block can't take the trip

                if best_block is None or cost < best_cost:
                    best_block = block
                    best_cost = cost
                    best_shift = required_shift
                    best_last_scheduled = last_scheduled

            scheduled_trip = ScheduledTrip(
                trip_id=trip.id,
                scheduled_start_time=trip.start_time + best_shift,
                scheduled_end_time=trip.end_time + best_shift,
            )

            if best_block is not None:
                best_block.add_trip(scheduled_trip)
                if best_block.vehicle_type == VehicleType.ELECTRIC:
                    idle_start = best_last_scheduled.scheduled_end_time + best_cost
                    idle_end = scheduled_trip.scheduled_start_time
                    best_block.try_charge_at_stop(self.instance, trip.origin_stop, idle_start, idle_end)
            else:
                params = self.instance.get_vehicle_type_params(preferred_type)
                max_blocks = params.max_virtual_blocks if params else None
                current_count = block_count_by_type.get(preferred_type, 0)

                if max_blocks is not None and current_count >= max_blocks:
                    solution.unassigned_trip_ids.append(trip.id)
                    continue
                depot = self._select_home_depot(preferred_type)
                if depot is None:
                    solution.unassigned_trip_ids.append(trip.id)
                    continue  # no depot has this vehicle type — can't open a block

                new_block = Block(id=f"block_{next_block_id}", depot_id=depot.id, vehicle_type=preferred_type)
                next_block_id += 1
                new_block.add_trip(scheduled_trip)
                blocks.append(new_block)
                block_count_by_type[preferred_type] = current_count + 1


        for block in blocks:
            solution.add_block(block)
            if not block.can_return_to_depot(self.instance):
                print(f"warning: {block.id} cannot return to its home depot ({block.depot_id})")

        return solution