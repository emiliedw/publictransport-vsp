from publictransport.io.loader import load_from_xml
from publictransport.solver import Solver
import time

instance = load_from_xml("data/Katowice_2026-26-3_15-08-26.xml")
print("trips loaded:", len(instance.trips))
print("deadheads created:", len(instance.deadheads))
print("depots loaded:", len(instance.depots))
print("chargers loaded:", len(instance.chargers))
print("vehicle type params loaded:", list(instance.vehicle_type_params.keys()))

for depot in instance.depots.values():
    print(f"  {depot.name}: {depot.fleet_capacity}")

solver = Solver(instance)
start_time = time.time()
solution_shift = solver.solve(trip_shifting=True)
solution_noshift = solver.solve(trip_shifting=False)
elapsed = time.time() - start_time



print(f"runtime: {elapsed:.2f} seconds")
solution_noshift.print_detailed_summary()
solution_noshift.export_gantt_json(r"C:\Users\emilie\IdeaProjects\public-transport\PublicTransport\results\gantt_seq_noshift.json")
solution_shift.export_gantt_json(r"C:\Users\emilie\IdeaProjects\public-transport\PublicTransport\results\gantt_seq_shift.json")