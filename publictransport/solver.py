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

    def solve(self, trip_shifting: bool = False) -> Solution:

        solution = Solution(instance=self.instance)

        trips = self.instance.get_trips_sorted_by_start_time()

        blocks: list[Block] = []
        next_block_id = 1
        home_depot = next(iter(self.instance.depots.values()), None)
        if home_depot is None:
            raise ValueError("No depot defined in this ProblemInstance — cannot assign a home depot to blocks.")

        for trip in trips:
            best_block = None
            best_cost = None
            best_shift = 0
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
                    required_shift = 0
                else:
                    required_shift = cost - gap
                    if required_shift > max_shift_sec:
                        continue

                if block.vehicle_type == VehicleType.ELECTRIC:
                    params = self.instance.get_vehicle_type_params(VehicleType.ELECTRIC)
                    consumed_so_far = block.energy_consumed_kwh(self.instance, params.consumption_kwh_per_km)
                    projected_consumed = consumed_so_far + (deadhead_km + trip.distance_km) * params.consumption_kwh_per_km
                    remaining_soc = params.battery_capacity_kwh - projected_consumed
                    min_soc_kwh = params.min_soc_fraction * params.battery_capacity_kwh
                    if remaining_soc < min_soc_kwh:
                        continue  # not enough range left, this block can't take the trip
                # --- end new ---

                if best_block is None or cost < best_cost:
                    best_block = block
                    best_cost = cost
                    best_shift = required_shift

            scheduled_trip = ScheduledTrip(
                trip_id=trip.id,
                scheduled_start_time=trip.start_time + best_shift,
                scheduled_end_time=trip.end_time + best_shift,
            )

            if best_block is not None:
                best_block.add_trip(scheduled_trip)
                if best_block.vehicle_type == VehicleType.ELECTRIC:
                    idle_start = last_scheduled.scheduled_end_time + best_cost  # after arriving (deadhead or none)
                    idle_end = scheduled_trip.scheduled_start_time
                    best_block.try_charge_at_stop(self.instance, trip.origin_stop, idle_start, idle_end)
            else:
                new_block = Block(id=f"block_{next_block_id}", depot_id=home_depot.id, vehicle_type=preferred_type)
                next_block_id += 1
                new_block.add_trip(scheduled_trip)
                blocks.append(new_block)

        for block in blocks:
            solution.add_block(block)
            if not block.can_return_to_depot(self.instance):
                print(f"warning: {block.id} cannot return to its home depot ({block.depot_id})")

        return solution