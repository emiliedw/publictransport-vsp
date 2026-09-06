from dataclasses import dataclass, field

from .instance import ProblemInstance
from .classes.block import Block
import json
from datetime import datetime, timedelta

@dataclass
class Solution:
    instance: ProblemInstance
    blocks: dict[str, Block] = field(default_factory=dict)
    unassigned_trip_ids: list[str] = field(default_factory=list)
    assigned_trip_ids: set= field(default_factory= set, repr=False)

    def add_block(self, block: Block) -> None:
        new_ids = {st.trip_id for st in block.scheduled_trips}
        overlap = self.assigned_trip_ids & new_ids
        if overlap:
            raise ValueError(f"Trip(s) already assigned to another block: {overlap}")
        self.assigned_trip_ids |= new_ids
        self.blocks[block.id] = block

    def validate_trip_assignment_integrity(self) -> None:
        assigned = {st.trip_id for b in self.blocks.values() for st in b.scheduled_trips}
        unassigned = set(self.unassigned_trip_ids)
        overlap = assigned & unassigned
        if overlap:
            raise ValueError(f"Trip(s) marked both assigned and unassigned: {overlap}")

        all_trip_ids = set(self.instance.trips.keys())
        missing = all_trip_ids - assigned - unassigned
        if missing:
            raise ValueError(f"Trip(s) neither assigned nor marked unassigned: {missing}")

    def num_blocks(self) -> int:
        return len(self.blocks)

    def print_full_schedule(self)->None: #will often be too much!
        for block in self.blocks.values():
            print(f"\n{block.id} ({len(block.scheduled_trips)} trips):")
            for scheduled in block.scheduled_trips:
                print(f" {scheduled.trip_id}: {scheduled.scheduled_start_time} ->{scheduled.scheduled_end_time}")

    def print_summary(self)->None:
        print(f"\ntotal blocks: {self.num_blocks()}")
        print(f"unassigned trips: {len(self.unassigned_trip_ids)}")

        block_sizes= sorted(
            (len(block.scheduled_trips) for block in self.blocks.values()),
            reverse=True,
        )
        print(f"trips per block (largest first): {block_sizes[:10]}{'...' if len(block_sizes) > 10 else ''}")
        print(f"average trips per block: {sum(block_sizes) / len(block_sizes):.1f}")
        gaps = self.fleet_gap_report()
        if gaps:
            print("\nfleet shortfalls (planned blocks exceed available vehicles):")
            for (depot_id, vehicle_type), shortfall in gaps.items():
                print(f"  depot {depot_id}, {vehicle_type.name}: short by {shortfall} vehicle(s)")

    def fleet_gap_report(self) -> dict[tuple[str, "VehicleType"], int]:
        planned_counts: dict[tuple[str, "VehicleType"], int] = {}
        for block in self.blocks.values():
            key = (block.depot_id, block.vehicle_type)
            planned_counts[key] = planned_counts.get(key, 0) + 1

        gaps = {}
        for (depot_id, vehicle_type), planned in planned_counts.items():
            depot = self.instance.get_depot(depot_id)
            available = depot.fleet_capacity.get(vehicle_type, 0) if depot else 0
            gap = planned - available
            if gap > 0:
                gaps[(depot_id, vehicle_type)] = gap
        return gaps




    def to_gantt_data(self, base_date: str = "2026-01-01") -> list[dict]:
        base = datetime.fromisoformat(base_date)

        def to_iso(seconds: int) -> str:
            return (base + timedelta(seconds=seconds)).isoformat()

        records = []
        for block in self.blocks.values():
            prev_trip = None
            prev_end = None

            for scheduled in block.scheduled_trips:
                trip = self.instance.get_trip(scheduled.trip_id)

            # Insert a deadhead bar if there's a gap between where the previous
            # trip ended and where this trip starts.
                if prev_trip is not None and prev_trip.destination_stop != trip.origin_stop:
                    records.append({
                        "block": block.id,
                        "vehicleType": block.vehicle_type.name,
                        "trip": "deadhead",
                        "startDate": to_iso(prev_end),
                        "endDate": to_iso(scheduled.scheduled_start_time),
                        "isDeadhead": True,
                        "description": f"Deadhead: {prev_trip.destination_stop} -> {trip.origin_stop}",
                    })

                records.append({
                    "block": block.id,
                    "vehicleType": block.vehicle_type.name,
                    "trip": f"{scheduled.trip_id} (Line {trip.line_id})",
                    "startDate": to_iso(scheduled.scheduled_start_time),
                    "endDate": to_iso(scheduled.scheduled_end_time),
                    "isDeadhead": False,
                    "description": (
                        f"Line {trip.line_id}, {trip.origin_stop} -> {trip.destination_stop}, "
                        f"direction {trip.direction}"
                    ),
                })

                prev_trip = trip
                prev_end = scheduled.scheduled_end_time

        return records


    def export_gantt_json(self, path: str = "gantt_data.json", base_date: str = "2026-01-01") -> None:
        """Write to_gantt_data() output to a JSON file, ready to paste into the Observable `tasks` cell."""
        import json
        data = self.to_gantt_data(base_date=base_date)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"exported {len(data)} records ({sum(not r['isDeadhead'] for r in data)} trips, "
              f"{sum(r['isDeadhead'] for r in data)} deadheads) to {path}")