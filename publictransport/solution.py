from dataclasses import dataclass, field
from .instance import ProblemInstance
from .classes.block import Block
from .classes.vehicle_type import VehicleType
from datetime import datetime, timedelta


@dataclass
class Solution:
    instance: ProblemInstance
    blocks: dict[str, Block] = field(default_factory=dict)
    unassigned_trip_ids: list[str] = field(default_factory=list)
    assigned_trip_ids: set = field(default_factory=set, repr=False)

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

    def print_summary(self) -> None:
        print(f"\ntotal blocks: {self.num_blocks()}")
        print(f"unassigned trips: {len(self.unassigned_trip_ids)}")

        block_sizes = sorted(
            (len(block.scheduled_trips) for block in self.blocks.values()),
            reverse=True,
        )
        print(f"trips per block (largest first): {block_sizes[:10]}{'...' if len(block_sizes) > 10 else ''}")
        print(f"average trips per block: {sum(block_sizes) / len(block_sizes):.1f}")

    def print_detailed_summary(self) -> None:
        blocks = list(self.blocks.values())
        num_blocks = len(blocks)
        num_trips = len(self.instance.trips)

        print("\n" + "=" * 60)
        print("SOLUTION SUMMARY")
        print("=" * 60)

        print(f"\nTotal trips in instance:      {num_trips}")
        print(f"Trips assigned to blocks:     {len(self.assigned_trip_ids)}")
        print(f"Unassigned trips:             {len(self.unassigned_trip_ids)}")
        print(f"Total blocks:                 {num_blocks}")

        if num_blocks == 0:
            print("\nNo blocks to summarize.")
            return

        block_sizes = [len(b.scheduled_trips) for b in blocks]
        print(f"\nTrips per block:")
        print(f"  min / avg / max:            {min(block_sizes)} / {sum(block_sizes)/num_blocks:.1f} / {max(block_sizes)}")

        durations_min = [b.duration_seconds() / 60 for b in blocks]
        print(f"\nBlock duration (minutes):")
        print(f"  min / avg / max:            {min(durations_min):.1f} / {sum(durations_min)/num_blocks:.1f} / {max(durations_min):.1f}")

        type_counts = {}
        for b in blocks:
            type_counts[b.vehicle_type] = type_counts.get(b.vehicle_type, 0) + 1
        print(f"\nBlocks by vehicle type:")
        for vt, count in sorted(type_counts.items(), key=lambda x: x[0].name):
            print(f"  {vt.name:15s}             {count}")

        depot_counts = {}
        for b in blocks:
            depot_counts[b.depot_id] = depot_counts.get(b.depot_id, 0) + 1
        print(f"\nBlocks by depot:")
        for depot_id, count in sorted(depot_counts.items()):
            depot = self.instance.get_depot(depot_id)
            name = depot.name if depot else depot_id
            print(f"  {name:25s}   {count}")

        total_deadheads = 0
        total_deadhead_km = 0.0
        for b in blocks:
            prev_trip = None
            for scheduled in b.scheduled_trips:
                trip = self.instance.get_trip(scheduled.trip_id)
                if prev_trip is not None and prev_trip.destination_stop != trip.origin_stop:
                    dh = self.instance.get_deadhead(prev_trip.destination_stop, trip.origin_stop)
                    if dh is not None:
                        total_deadheads += 1
                        total_deadhead_km += dh.distance_km
                prev_trip = trip
        print(f"\nDeadhead trips:                {total_deadheads}")
        print(f"Total deadhead distance (km):  {total_deadhead_km:.1f}")

        total_line_changes = sum(b.count_line_changes(self.instance) for b in blocks)
        print(f"\nLine changes total:            {total_line_changes}")
        print(f"Line changes per block (avg):  {total_line_changes/num_blocks:.2f}")

        direction_violations = sum(1 for b in blocks if b.has_direction_violation(self.instance))
        cannot_return = sum(1 for b in blocks if not b.can_return_to_depot(self.instance))
        below_minimum = sum(1 for b in blocks if not b.meets_minimum_requirements(self.instance))
        print(f"\nBlocks with direction violations:      {direction_violations}")
        print(f"Blocks that cannot return to depot:    {cannot_return}")
        print(f"Blocks below minimum requirements:     {below_minimum}")

        num_short = sum(1 for b in blocks if b.is_short_block(self.instance))
        num_single = sum(1 for b in blocks if b.is_single_trip_block())
        print(f"\nShort blocks (< {self.instance.short_block_trip_threshold} trips):        {num_short}")
        print(f"Single-trip blocks:                    {num_single}")

        total_shift = sum(b.total_shift_seconds(self.instance) for b in blocks)
        shifted_trip_count = sum(
            1 for b in blocks for st in b.scheduled_trips
            if st.scheduled_start_time != self.instance.get_trip(st.trip_id).start_time
        )
        print(f"\nTrips shifted from original time:      {shifted_trip_count}")
        print(f"Total shift amount (minutes):          {total_shift/60:.1f}")
        if shifted_trip_count:
            print(f"Average shift per shifted trip (sec):  {total_shift/shifted_trip_count:.1f}")

        electric_blocks = [b for b in blocks if b.vehicle_type == VehicleType.ELECTRIC]
        if electric_blocks:
            params = self.instance.get_vehicle_type_params(VehicleType.ELECTRIC)
            total_kwh = (
                sum(b.energy_consumed_kwh(self.instance, params.consumption_profile) for b in electric_blocks)
                if params else 0.0
            )
            total_charging_events = sum(len(b.charging_events) for b in electric_blocks)
            print(f"\nElectric blocks:                       {len(electric_blocks)}")
            print(f"Total energy consumed (kWh):           {total_kwh:.1f}")
            print(f"Total charging events:                 {total_charging_events}")

        print("=" * 60 + "\n")

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
        import json
        data = self.to_gantt_data(base_date=base_date)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"exported {len(data)} records ({sum(not r['isDeadhead'] for r in data)} trips, "
              f"{sum(r['isDeadhead'] for r in data)} deadheads) to {path}")