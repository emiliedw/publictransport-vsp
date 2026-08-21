from .instance import ProblemInstance
from .solution import Solution
from .objective import ObjectiveFunction


class Solver:
    def __init__(self, instance: ProblemInstance, objective: ObjectiveFunction) -> None:
        self.instance = instance
        self.objective = objective

    def solve(self) -> Solution:
        """
        Build a Solution from self.instance.

        This is where your constructive algorithm goes, e.g.:
        - sort/iterate over self.instance.trips
        - greedily assign each trip to an existing or new Block
        - respect depot, range/SoC, and break-time constraints
        - fall back to self instance's deadheads for empty-running legs

        Return a populated Solution.
        """
        solution = Solution(instance=self.instance)
        # TODO: your algorithm here
        return solution