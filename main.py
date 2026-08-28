from publictransport.io.loader import load_from_xml
from publictransport.objective import ObjectiveWeights, ObjectiveFunction
from publictransport.solver import Solver
import time

instance = load_from_xml("data/Katowice_2026-26-3_15-08-26.xml")
print("trips loaded:", len(instance.trips))
print("deadheads created:", len(instance.deadheads))

weights = ObjectiveWeights()
objective = ObjectiveFunction(weights)

solver = Solver(instance, objective)
start_time=time.time()
solution = solver.solve()
elapsed= time.time()-start_time

print(f"blocks created: {solution.num_blocks()}")
print(f"runtime: {elapsed:.2f} seconds")
solution.print_summary()