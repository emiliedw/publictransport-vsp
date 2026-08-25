#AI USED!!!

import unittest

from publictransport.classes.trip import Trip
from publictransport.classes.deadhead_trip import DeadheadTrip
from publictransport.instance import ProblemInstance
from publictransport.objective import ObjectiveWeights, ObjectiveFunction
from publictransport.solver import Solver


class TestSolver(unittest.TestCase):

    #two  trips. trip 2 starts where trip 1 ends with big time gap
    def test_two_compatible_trips_form_one_block(self):
        instance = ProblemInstance()

        instance.add_trip(Trip(
            id="t1", line_id="L1",
            start_time=0, end_time=600,
            direction="", origin_stop="A", destination_stop="B",
        ))
        instance.add_trip(Trip(
            id="t2", line_id="L1",
            start_time=700, end_time=1200,
            direction="", origin_stop="B", destination_stop="C",
        ))
        # t1 ends at B, t2 starts at B -> no deadhead needed, 100s gap is enough

        objective = ObjectiveFunction(ObjectiveWeights())
        solver = Solver(instance, objective)
        solution = solver.solve()

        self.assertEqual(solution.num_blocks(), 1)

    #two trips. trip 2 starts at different stop than the stop of trip1 and no deadheadtrip connects the two stops
    def test_two_incompatible_trips_form_two_blocks(self):
        instance = ProblemInstance()

        instance.add_trip(Trip(
            id="t1", line_id="L1",
            start_time=0, end_time=600,
            direction="", origin_stop="A", destination_stop="B",
        ))
        instance.add_trip(Trip(
            id="t2", line_id="L1",
            start_time=650, end_time=1200,  # only 50s gap
            direction="", origin_stop="X", destination_stop="Y",
        ))
        # no deadhead defined between B and X -> incompatible

        objective = ObjectiveFunction(ObjectiveWeights())
        solver = Solver(instance, objective)
        solution = solver.solve()

        self.assertEqual(solution.num_blocks(), 2)


        def test_deadhead_exists_but_gap_too_tight_forms_two_blocks(self):
            instance = ProblemInstance()

        instance.add_trip(Trip(
            id="t1", line_id="L1",
            start_time=0, end_time=600,
            direction="", origin_stop="A", destination_stop="B",
        ))
        instance.add_trip(Trip(
            id="t2", line_id="L1",
            start_time=620, end_time=1200,  # only 20s gap after t1
            direction="", origin_stop="X", destination_stop="Y",
        ))
        # a deadhead DOES exist from B to X, but it takes 60s — more than the 20s gap
        instance.add_deadhead(DeadheadTrip(
            origin_stop="B", destination_stop="X",
            duration_minutes=1.0, distance_km=0.5,
        ))

        objective = ObjectiveFunction(ObjectiveWeights())
        solver = Solver(instance, objective)
        solution = solver.solve()

        self.assertEqual(solution.num_blocks(), 2)

    def test_smallest_deadhead_wins_among_candidates(self):
        instance = ProblemInstance()

        # two independent first trips -> each opens its own block
        instance.add_trip(Trip(
            id="t1", line_id="L1",
            start_time=0, end_time=600,
            direction="", origin_stop="A", destination_stop="B",
        ))
        instance.add_trip(Trip(
            id="t2", line_id="L1",
            start_time=0, end_time=600,
            direction="", origin_stop="C", destination_stop="D",
        ))

        # t3 is reachable from both blocks, but cheaper from D (t2's block) than from B (t1's block)
        instance.add_trip(Trip(
            id="t3", line_id="L1",
            start_time=1000, end_time=1600,
            direction="", origin_stop="E", destination_stop="F",
        ))
        instance.add_deadhead(DeadheadTrip(
            origin_stop="B", destination_stop="E",
            duration_minutes=2.0, distance_km=1.0,  # 120s
        ))
        instance.add_deadhead(DeadheadTrip(
            origin_stop="D", destination_stop="E",
            duration_minutes=1.0, distance_km=0.5,  # 60s, cheaper
        ))

        objective = ObjectiveFunction(ObjectiveWeights())
        solver = Solver(instance, objective)
        solution = solver.solve()

        self.assertEqual(solution.num_blocks(), 2)

        # find which block t3 ended up in, and check it's the 2-trip one (t2's block)
        block_sizes = sorted(len(block.scheduled_trips) for block in solution.blocks.values())
        self.assertEqual(block_sizes, [1, 2])


if __name__ == "__main__":
    unittest.main()