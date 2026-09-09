from dataclasses import dataclass, field

from .instance import ProblemInstance
from .classes.block import Block
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

    def summary_dict(self, objective: "ObjectiveFunction" = None) -> dict:
        from .classes.vehicle_type import VehicleType

        blocks = list(self.blocks.values())
        num_blocks = len(blocks)
        num_trips = len(self.instance.trips)

        if num_blocks == 0:
            return {"totalBlocks": 0, "totalTripsInInstance": num_trips}

        block_sizes = [len(b.scheduled_trips) for b in blocks]
        durations_min = [b.duration_seconds() / 60 for b in blocks]

        type_counts = {}
        for b in blocks:
            type_counts[b.vehicle_type.name] = type_counts.get(b.vehicle_type.name, 0) + 1

        depot_counts = {}
        for b in blocks:
            depot = self.instance.get_depot(b.depot_id)
            name = depot.name if depot else b.depot_id
            depot_counts[name] = depot_counts.get(name, 0) + 1

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

        total_line_changes = sum(b.count_line_changes(self.instance) for b in blocks)
        total_line_change_penalty = sum(b.line_change_penalty(self.instance) for b in blocks)

        total_shift = sum(b.total_shift_seconds(self.instance) for b in blocks)
        shifted_trip_count = sum(
            1 for b in blocks for st in b.scheduled_trips
            if st.scheduled_start_time != self.instance.get_trip(st.trip_id).start_time
        )

        electric_blocks = [b for b in blocks if b.vehicle_type == VehicleType.ELECTRIC]
        total_kwh = 0.0
        if electric_blocks:
            params = self.instance.get_vehicle_type_params(VehicleType.ELECTRIC)
            if params:
                total_kwh = sum(
                    b.energy_consumed_kwh(self.instance, params.consumption_profile)
                    for b in electric_blocks
                )

        result = {
            "totalTripsInInstance": num_trips,
            "tripsAssigned": len(self.assigned_trip_ids),
            "unassignedTrips": len(self.unassigned_trip_ids),
            "totalBlocks": num_blocks,
            "tripsPerBlock": {
                "min": min(block_sizes),
                "avg": sum(block_sizes) / num_blocks,
                "max": max(block_sizes),
            },
            "blockDurationMinutes": {
                "min": min(durations_min),
                "avg": sum(durations_min) / num_blocks,
                "max": max(durations_min),
            },
            "blocksByVehicleType": type_counts,
            "blocksByDepot": depot_counts,
            "deadheadTrips": total_deadheads,
            "totalDeadheadKm": total_deadhead_km,
            "lineChangesTotal": total_line_changes,
            "avgLineChangesPerBlock": total_line_changes / num_blocks,
            "lineChangePenalty": total_line_change_penalty,
            "blocksWithDirectionViolations": sum(1 for b in blocks if b.has_direction_violation(self.instance)),
            "blocksThatCannotReturnToDepot": sum(1 for b in blocks if not b.can_return_to_depot(self.instance)),
            "blocksBelowMinimumRequirements": sum(1 for b in blocks if not b.meets_minimum_requirements(self.instance)),
            "shortBlocks": sum(1 for b in blocks if b.is_short_block(self.instance)),
            "singleTripBlocks": sum(1 for b in blocks if b.is_single_trip_block()),
            "shiftedTrips": shifted_trip_count,
            "totalShiftMinutes": total_shift / 60,
            "avgShiftSeconds": (total_shift / shifted_trip_count) if shifted_trip_count else 0.0,
            "environmentalKwh": total_kwh,
        }

        if objective is not None:
            result["objectiveScore"] = objective.evaluate(self)
            result["environmentalKwhObjective"] = objective.environmental_kpi(self)

        return result




    def print_detailed_summary(self, objective: "ObjectiveFunction" = None) -> None:
        """A fuller report than print_summary(): block stats, deadheads, line changes,
        constraint sanity checks, trip shifting, electric fleet KPIs, and (optionally)
        the weighted objective score if an ObjectiveFunction is passed in."""
        from .classes.vehicle_type import VehicleType

        blocks = list(self.blocks.values())
        num_blocks = len(blocks)
        num_trips = len(self.instance.trips)

        print("\n" + "=" * 60)
        print("SOLUTION SUMMARY")
        print("=" * 60)

        # ---- Basic counts ----
        print(f"\nTotal trips in instance:      {num_trips}")
        print(f"Trips assigned to blocks:     {len(self.assigned_trip_ids)}")
        print(f"Unassigned trips:             {len(self.unassigned_trip_ids)}")
        print(f"Total blocks:                 {num_blocks}")
        num_one_trip_blocks = sum(1 for b in self.blocks.values() if b.is_single_trip_block())
        print(f"one-trip blocks: {num_one_trip_blocks}")


        if num_blocks == 0:
            print("\nNo blocks to summarize.")
            return

        # ---- Block size stats ----
        block_sizes = [len(b.scheduled_trips) for b in blocks]
        print(f"\nTrips per block:")
        print(f"  min / avg / max:            {min(block_sizes)} / {sum(block_sizes)/num_blocks:.1f} / {max(block_sizes)}")

        # ---- Duration stats ----
        durations_min = [b.duration_seconds() / 60 for b in blocks]
        print(f"\nBlock duration (minutes):")
        print(f"  min / avg / max:            {min(durations_min):.1f} / {sum(durations_min)/num_blocks:.1f} / {max(durations_min):.1f}")

        # ---- Vehicle type breakdown ----
        type_counts = {}
        for b in blocks:
            type_counts[b.vehicle_type] = type_counts.get(b.vehicle_type, 0) + 1
        print(f"\nBlocks by vehicle type:")
        for vt, count in sorted(type_counts.items(), key=lambda x: x[0].name):
            print(f"  {vt.name:15s}             {count}")

        # ---- Depot breakdown ----
        depot_counts = {}
        for b in blocks:
            depot_counts[b.depot_id] = depot_counts.get(b.depot_id, 0) + 1
        print(f"\nBlocks by depot:")
        for depot_id, count in sorted(depot_counts.items()):
            depot = self.instance.get_depot(depot_id)
            name = depot.name if depot else depot_id
            print(f"  {name:25s}   {count}")

        # ---- Deadhead stats ----
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

        # ---- Line changes ----
        total_line_changes = sum(b.count_line_changes(self.instance) for b in blocks)
        total_line_change_penalty = sum(b.line_change_penalty(self.instance) for b in blocks)
        print(f"\nLine changes total:            {total_line_changes}")
        print(f"Line changes per block (avg):  {total_line_changes/num_blocks:.2f}")
        print(f"Line change penalty (sum):     {total_line_change_penalty:.1f}")

        # ---- Hard-constraint sanity checks ----
        direction_violations = sum(1 for b in blocks if b.has_direction_violation(self.instance))
        cannot_return = sum(1 for b in blocks if not b.can_return_to_depot(self.instance))
        below_minimum = sum(1 for b in blocks if not b.meets_minimum_requirements(self.instance))
        print(f"\nBlocks with direction violations:      {direction_violations}")
        print(f"Blocks that cannot return to depot:    {cannot_return}")
        print(f"Blocks below minimum requirements:     {below_minimum}")

        # ---- Short / single-trip blocks ----
        num_short = sum(1 for b in blocks if b.is_short_block(self.instance))
        num_single = sum(1 for b in blocks if b.is_single_trip_block())
        print(f"\nShort blocks (< {self.instance.short_block_trip_threshold} trips):        {num_short}")
        print(f"Single-trip blocks:                    {num_single}")

        # ---- Trip shifting ----
        total_shift = sum(b.total_shift_seconds(self.instance) for b in blocks)
        shifted_trip_count = sum(
            1 for b in blocks for st in b.scheduled_trips
            if st.scheduled_start_time != self.instance.get_trip(st.trip_id).start_time
        )
        print(f"\nTrips shifted from original time:      {shifted_trip_count}")
        print(f"Total shift amount (minutes):          {total_shift/60:.1f}")
        if shifted_trip_count:
            print(f"Average shift per shifted trip (sec):  {total_shift/shifted_trip_count:.1f}")

        # ---- Electric fleet / energy KPIs ----
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

        # ---- Fleet capacity gaps ----
        gaps = self.fleet_gap_report()
        if gaps:
            print(f"\nFleet shortfalls (planned exceeds available):")
            for (depot_id, vehicle_type), shortfall in gaps.items():
                print(f"  depot {depot_id}, {vehicle_type.name}: short by {shortfall}")

        # ---- Objective score (optional) ----
        if objective is not None:
            score = objective.evaluate(self)
            env_kpi = objective.environmental_kpi(self)
            print(f"\nObjective score (weighted, normalized 0-1): {score:.4f}")
            print(f"Environmental KPI (total electric kWh):     {env_kpi:.1f}")

        print("=" * 60 + "\n")

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
                    "originalStartDate": to_iso(trip.start_time),
                    "isDeadhead": False,
                    "description": (
                        f"Line {trip.line_id}, {trip.origin_stop} -> {trip.destination_stop}, "
                        f"direction {trip.direction}"
                    ),
                })

                prev_trip = trip
                prev_end = scheduled.scheduled_end_time

        return records


    def export_gantt_json(self, path: str = "gantt_data.json", base_date: str = "2026-01-01",
                          objective: "ObjectiveFunction" = None) -> None:
        """Write {summary, trips} to a JSON file for the Observable notebook."""
        import json
        trips = self.to_gantt_data(base_date=base_date)
        payload = {
            "summary": self.summary_dict(objective=objective),
            "trips": trips,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"exported {len(trips)} records ({sum(not r['isDeadhead'] for r in trips)} trips, "
              f"{sum(r['isDeadhead'] for r in trips)} deadheads) to {path}")