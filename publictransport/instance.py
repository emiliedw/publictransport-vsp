from dataclasses import dataclass, field
from typing import Optional

from .classes.depot import Depot
from .classes.line import Line
from .classes.trip import Trip
from .classes.vehicle import Vehicle
from .classes.charger import Charger
from .classes.deadhead_trip import DeadheadTrip
from .classes.vehicle_type import VehicleType
from .classes.vehicle_type_params import VehicleTypeParams
from .classes.timetable_zone import TimetableZones


@dataclass
class ProblemInstance:
    # ---- core registries ----
    depots: dict[str, Depot] = field(default_factory=dict)
    lines: dict[str, Line] = field(default_factory=dict)
    trips: dict[str, Trip] = field(default_factory=dict)
    vehicles: dict[str, Vehicle] = field(default_factory=dict)
    chargers: dict[str, Charger] = field(default_factory=dict)
    deadheads: dict[tuple[str, str], DeadheadTrip] = field(default_factory=dict)  # (origin, destination) -> DeadheadTrip
    vehicle_type_params: dict[VehicleType, VehicleTypeParams] = field(default_factory=dict)

    # ---- operating day / timetable zones ----
    operating_day_start_seconds: int = 5 * 3600
    timetable_zones: Optional[TimetableZones] = None

    # ---- deadhead speed model ----
    base_deadhead_speed_kmh: float = 25.0   # assumed operating speed for empty runs
    deadhead_speed_coefficients: dict[int, float] = field(default_factory=dict)  # zone_index -> multiplier

    # ---- charger occupancy ----
    charger_bookings: dict[str, list[tuple[int, int]]] = field(default_factory=dict)  # charger_id -> [(start, end)]

    # ---- block sizing thresholds ----
    min_block_trips: int = 1
    min_block_duration_seconds: int = 0
    short_block_trip_threshold: int = 2

    # ---- breaks ----
    split_block_min_break_seconds: int = 90 * 60
    max_single_trip_break_seconds: Optional[int] = None   # pbmax
    br_max_seconds: Optional[int] = None                   # break length that triggers depot-return rule
    depot_return_policy: int = 1                           # 1 = home depot, 2 = any depot, 3 = secured terminus
    stops_with_secured_parking: set[str] = field(default_factory=set)

    # ---- statutory driver breaks ----
    stops_with_driver_facilities: set[str] = field(default_factory=set)
    duty_break_thresholds: list[tuple[int, int]] = field(default_factory=lambda: [
        (6 * 3600, 30 * 60),   # over 6h duty -> 30 min break required
        (8 * 3600, 45 * 60),   # over 8h duty -> 45 min break required
    ])
    min_break_component_seconds: int = 15 * 60   # smallest break segment that counts (allows 3x15, 30+15, etc.)

    # ---- line changes ----
    max_line_changes_per_block: Optional[int] = None   # lzmax
    line_change_preferences: dict[tuple[str, str], float] = field(default_factory=dict)  # (from_line, to_line) -> [0,10]

    # ---- registration ----

    def add_depot(self, depot: Depot) -> None:
        self.depots[depot.id] = depot

    def add_line(self, line: Line) -> None:
        self.lines[line.id] = line

    def add_trip(self, trip: Trip) -> None:
        self.trips[trip.id] = trip

    def add_vehicle(self, vehicle: Vehicle) -> None:
        self.vehicles[vehicle.id] = vehicle

    def add_charger(self, charger: Charger) -> None:
        self.chargers[charger.id] = charger

    def add_deadhead(self, deadhead: DeadheadTrip) -> None:
        self.deadheads[(deadhead.origin_stop, deadhead.destination_stop)] = deadhead

    def add_vehicle_type_params(self, params: VehicleTypeParams) -> None:
        self.vehicle_type_params[params.vehicle_type] = params

    # ---- getters ----

    def get_trip(self, trip_id: str) -> Optional[Trip]:
        return self.trips.get(trip_id)

    def get_depot(self, depot_id: str) -> Optional[Depot]:
        return self.depots.get(depot_id)

    def get_vehicle(self, vehicle_id: str) -> Optional[Vehicle]:
        return self.vehicles.get(vehicle_id)

    def get_line(self, line_id: str) -> Optional[Line]:
        return self.lines.get(line_id)

    def get_deadhead(self, origin_stop: str, destination_stop: str) -> Optional[DeadheadTrip]:
        return self.deadheads.get((origin_stop, destination_stop))

    def get_vehicle_type_params(self, vehicle_type: VehicleType) -> Optional[VehicleTypeParams]:
        return self.vehicle_type_params.get(vehicle_type)

    def get_chargers_at_location(self, location_id: str) -> list[Charger]:
        return [c for c in self.chargers.values() if c.location_id == location_id]

    def is_at_any_depot(self, stop_id: str) -> bool:
        return any(depot.location_stop_id == stop_id for depot in self.depots.values())

    # ---- sorters ----

    def get_trips_sorted_by_start_time(self) -> list[Trip]:
        return sorted(self.trips.values(), key=lambda trip: trip.start_time)

    def get_trips_sorted_by_end_time(self) -> list[Trip]:
        return sorted(self.trips.values(), key=lambda trip: trip.end_time)

    # ---- time helpers ----

    def seconds_since_day_start(self, time_seconds: int) -> int:
        return (time_seconds - self.operating_day_start_seconds) % 86400

    # ---- deadhead duration model ----

    def get_deadhead_duration_seconds(self, origin_stop: str, destination_stop: str, at_time_seconds: int) -> Optional[float]:
        deadhead = self.get_deadhead(origin_stop, destination_stop)
        if deadhead is None:
            return None

        speed = self.base_deadhead_speed_kmh
        if self.timetable_zones is not None:
            zone_idx = self.timetable_zones.zone_index(at_time_seconds)
            speed *= self.deadhead_speed_coefficients.get(zone_idx, 1.0)

        if speed <= 0:
            return None

        hours = deadhead.distance_km / speed
        return hours * 3600

    # ---- charger occupancy ----

    def is_charger_free(self, charger_id: str, window_start: int, window_end: int) -> bool:
        return all(
            window_end <= booked_start or booked_end <= window_start
            for booked_start, booked_end in self.charger_bookings.get(charger_id, [])
        )

    def book_charger(self, charger_id: str, window_start: int, window_end: int) -> None:
        self.charger_bookings.setdefault(charger_id, []).append((window_start, window_end))

    # ---- break intervals ----

    def get_break_interval(self, trip, vehicle_type) -> tuple[int, Optional[int]]:
        """Resolve (tmin, tmax) for the break after a trip: trip override > line default > vehicle-type fallback."""
        if trip.min_break_seconds is not None or trip.max_break_seconds is not None:
            return trip.min_break_seconds or 0, trip.max_break_seconds

        line = self.get_line(trip.line_id)
        if line is not None and (line.default_min_break_seconds is not None or line.default_max_break_seconds is not None):
            return line.default_min_break_seconds or 0, line.default_max_break_seconds

        params = self.get_vehicle_type_params(vehicle_type)
        if params is None:
            return 0, None
        return params.min_break_seconds, params.max_break_seconds

    # ---- line-change preferences ----

    def get_line_change_penalty(self, from_line_id: str, to_line_id: str) -> float:
        if from_line_id == to_line_id:
            return 0.0
        return self.line_change_preferences.get((from_line_id, to_line_id), 10.0)

    def is_line_change_allowed(self, from_line_id: str, to_line_id: str) -> bool:
        if from_line_id == to_line_id:
            return True
        return self.line_change_preferences.get((from_line_id, to_line_id)) != 0