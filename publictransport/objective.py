from dataclasses import dataclass

from .solution import Solution

'''the thing that needs to be minimized/maximized
here:   number of blocks used: minimized
        number of line changes within blocks: minimized
        number of unassigned trips: minimized
        
combine all these into 1 weighted number. lower = better solution

objectiveweights: how much does each component matter? now: equal
objectivefunction: takes a solution and calculates the score


THIS WILL BE IMPORTANT IF WE WANT TO IMPROVE THE INITIAL SOLUTION LATER ON
'''
@dataclass
class ObjectiveWeights:
    num_blocks: float = 1.0
    num_line_changes: float = 1.0
    num_unassigned_trips: float = 0.0
    num_statutory_break_violations: float = 1.0


class ObjectiveFunction:
    def __init__(self, weights: ObjectiveWeights) -> None:
        self.weights = weights

    def evaluate(self, solution: Solution) -> float:
        num_blocks = solution.num_blocks()
        num_line_changes = sum(
            block.count_line_changes(solution.instance) for block in solution.blocks.values()
        )
        num_unassigned = len(solution.unassigned_trip_ids)
        num_break_violations = sum(
            block.count_statutory_break_violations(solution.instance) for block in solution.blocks.values()
        )

        return (
                self.weights.num_blocks * num_blocks
                + self.weights.num_line_changes * num_line_changes
                + self.weights.num_unassigned_trips * num_unassigned
                + self.weights.num_statutory_break_violations * num_break_violations
        )