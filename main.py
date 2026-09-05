from publictransport.io.loader import load_from_xml
from publictransport.objective import ObjectiveWeights, ObjectiveFunction
from publictransport.solver import Solver
from publictransport.classes import VehicleType
from publictransport.classes.depot import Depot
from collections import Counter
import time

instance = load_from_xml("data/Katowice_2026-26-3_15-08-26.xml")
print("trips loaded:", len(instance.trips))
print("deadheads created:", len(instance.deadheads))

destination_counts = Counter(trip.destination_stop for trip in instance.trips.values())
top_destinations = destination_counts.most_common(10)
print("top destination stops:", top_destinations)

for stop_id, _ in top_destinations:
    reachable = sum(
        1 for trip in instance.trips.values()
        if trip.destination_stop == stop_id
        or instance.get_deadhead(trip.destination_stop, stop_id) is not None
    )
    print(f"  {stop_id}: {reachable} / {len(instance.trips)} trips could return here")

best_depot_stop = top_destinations[0][0]  # 62df6025-... from your results, 2851/2851 reachable

instance.add_depot(Depot(
    id="depot_1",
    name="Placeholder Depot",
    location_stop_id=best_depot_stop,
    fleet_capacity={VehicleType.CONVENTIONAL: 9999},
))

weights = ObjectiveWeights()
objective = ObjectiveFunction(weights)

solver = Solver(instance, objective)
start_time = time.time()
solution = solver.solve()
elapsed = time.time() - start_time

print(f"blocks created: {solution.num_blocks()}")
print(f"runtime: {elapsed:.2f} seconds")
solution.print_summary()