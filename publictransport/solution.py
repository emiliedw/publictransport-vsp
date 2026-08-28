from dataclasses import dataclass, field

from .instance import ProblemInstance
from .classes.block import Block


@dataclass
class Solution:
    instance: ProblemInstance
    blocks: dict[str, Block] = field(default_factory=dict)
    unassigned_trip_ids: list[str] = field(default_factory=list)

    def add_block(self, block: Block) -> None:
        self.blocks[block.id] = block

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