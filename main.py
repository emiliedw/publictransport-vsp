from publictransport.io.loader import load_from_xml
from publictransport.objective import ObjectiveWeights, ObjectiveFunction
from publictransport.solver import Solver

instance = load_from_xml("data/Katowice_2026-26-3_15-08-26.xml")
print("trips loaded:", len(instance.trips))
print("deadheads loaded:", len(instance.deadheads))

weights = ObjectiveWeights()
objective = ObjectiveFunction(weights)

solver = Solver(instance, objective)
solution = solver.solve()

print("blocks created:", solution.num_blocks())