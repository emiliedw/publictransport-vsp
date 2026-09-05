from publictransport.io.loader import load_from_xml
from publictransport.objective import ObjectiveWeights, ObjectiveFunction
from publictransport.solver import Solver
import time
from publictransport.classes import VehicleType

from publictransport.classes.depot import Depot

instance = load_from_xml("data/Katowice_2026-26-3_15-08-26.xml")
instance.add_depot(Depot(
    id="depot_1",
    name="Placeholder Depot",
    location_stop_id="???",
    fleet_capacity={VehicleType.CONVENTIONAL: 9999},
))
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