from .instance import ProblemInstance
from .solution import Solution
from .objective import ObjectiveFunction
from .classes.block import Block
from .classes.trip import ScheduledTrip


class Solver:

    ## input: list op trips, deadhead table
    ## output: list of blocks

    def __init__(self, instance: ProblemInstance, objective: ObjectiveFunction) -> None:
        self.instance = instance
        self.objective = objective

    def solve(self, trip_shifting: bool=False)-> Solution:

        solution= Solution(instance=self.instance)

        ## STEP 1: sort trips by ascending start_time
        trips= self.instance.get_trips_sorted_by_start_time()

        ## STEP 2: create an empty list of blocks
        blocks: list[Block]= []
        next_block_id= 1

        ## STEP 3: walk through trips in time order, for each one: slot it into the bus that reaches it soones or start a new bus if none can
        ## for each trip
        ##    best_block <- none
        ##    best_cost <- none
        ##    for each existing block:
        ##
        for trip in trips:
            best_block= None
            best_cost= None
            best_shift= 0 #time shift
            max_shift_sec= trip.max_shift_minutes*60 if trip_shifting else 0

            for block in blocks:
                last_scheduled= block.scheduled_trips[-1]
                last_trip= self.instance.get_trip(last_scheduled.trip_id)

                if last_trip.destination_stop== trip.origin_stop: #no deadhead needed
                    cost= 0
                else:
                    deadhead= self.instance.get_deadhead(
                        last_trip.destination_stop, trip.origin_stop
                    )
                    if deadhead is None:
                        continue #incompatible: you can't reach it
                    cost= deadhead.duration_minutes*60 #turn minutes to seconds

                gap= trip.start_time-last_scheduled.scheduled_end_time

                if gap>=cost:
                    required_shift=0
                else:
                    required_shift=cost-gap
                    if required_shift>max_shift_sec:
                        continue

                if best_block is None or cost<best_cost:
                    best_block= block
                    best_cost= cost
                    best_shift= required_shift

            scheduled_trip= ScheduledTrip(
                trip_id= trip.id,
                scheduled_start_time=trip.start_time+best_shift,
                scheduled_end_time=trip.end_time+best_shift,

            )

            #if best block is found: add it, else: create new block
            if best_block is not None:
                best_block.add_trip(scheduled_trip)
            else:
                new_block= Block(id=f"block_{next_block_id}", vehicle_id="", depot_id="")
                next_block_id+=1
                new_block.add_trip(scheduled_trip)
                blocks.append(new_block)

        ## STEP 4: return the blocks
        for block in blocks:
            solution.add_block(block)

        return solution