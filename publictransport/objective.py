from dataclasses import dataclass

from .solution import Solution


@dataclass
class ObjectiveWeights:
    num_blocks: float = 1.0
    num_line_changes: float = 1.0
    num_unassigned_trips: float = 0.0


class ObjectiveFunction:
    def __init__(self, weights: ObjectiveWeights) -> None:
        self.weights = weights

    def evaluate(self, solution: Solution) -> float:
        """Compute the weighted objective value for a solution."""
        raise NotImplementedError