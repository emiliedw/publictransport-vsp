from dataclasses import dataclass, field
from .trip import ScheduledTrip
from .charging_event import ChargingEvent
from .vehicle_type import VehicleType
from .charging_event import ChargingEvent

class Block:
    def __init__(self, id: str, depot_id: str, vehicle_type: VehicleType, vehicle_id: str = ""):
        self.id = id
        self.depot_id = depot_id
        self.vehicle_type = vehicle_type
        self.vehicle_id = vehicle_id
        self.scheduled_trips = []
        self.charging_events = []

    def add_trip(self, scheduled_trip) -> None:
        self.scheduled_trips.append(scheduled_trip)

    def add_charging_event(self, event) -> None:
        self.charging_events.append(event)

    def can_return_to_depot(self, instance) -> bool:
        """Hard constraint 4: a block must end at the same depot it started from."""
        if not self.scheduled_trips:
            return True  # nothing scheduled yet, nothing to check

        depot = instance.get_depot(self.depot_id)
        if depot is None:
            return False

        last_scheduled = self.scheduled_trips[-1]
        last_trip = instance.get_trip(last_scheduled.trip_id)

        if last_trip.destination_stop == depot.location_stop_id:
            return True  # already sitting at the depot

        deadhead = instance.get_deadhead(last_trip.destination_stop, depot.location_stop_id)
        return deadhead is not None

    def count_line_changes(self, instance) -> int:
        """Number of times consecutive trips in this block switch lines."""
        changes = 0
        prev_line_id = None
        for scheduled in self.scheduled_trips:
            trip = instance.get_trip(scheduled.trip_id)
            if prev_line_id is not None and trip.line_id != prev_line_id:
                changes += 1
            prev_line_id = trip.line_id
        return changes

    def energy_consumed_kwh(self, instance, consumption_profile) -> float:
        total_kwh = 0.0
        prev_trip = None

        for scheduled in self.scheduled_trips:
            trip = instance.get_trip(scheduled.trip_id)
            hour = (instance.seconds_since_day_start(scheduled.scheduled_start_time) // 3600) % 24

            if prev_trip is not None and prev_trip.destination_stop != trip.origin_stop:
                deadhead = instance.get_deadhead(prev_trip.destination_stop, trip.origin_stop)
                if deadhead is not None:
                    rate = consumption_profile.consumption_kwh_per_km(hour=hour)
                    total_kwh += deadhead.distance_km * rate

            rate = consumption_profile.consumption_kwh_per_km(line_id=trip.line_id, hour=hour)
            total_kwh += trip.distance_km * rate

            prev_trip = trip
        return total_kwh

    def remaining_soc_kwh(self, instance, params) -> float:
        return params.battery_capacity_kwh - self.energy_consumed_kwh(instance, params.consumption_profile)

    def try_charge_at_stop(self, instance, stop_id: str, window_start: int, window_end: int) -> bool:
        available_seconds = window_end - window_start
        if available_seconds <= 0:
            return False

        for charger in instance.get_chargers_at_location(stop_id):
            if not charger.is_available(window_start, window_end, instance.operating_day_start_seconds):
                continue

            min_needed_seconds = charger.min_charging_minutes * 60
            if available_seconds < min_needed_seconds:
                continue

            if not instance.is_charger_free(charger.id, window_start, window_end):
                continue  # NEW — another vehicle is already using this charger during this window

            energy_added = (available_seconds / 3600) * charger.charging_rate_kw
            self.add_charging_event(ChargingEvent(
                vehicle_id=self.vehicle_id,
                charger_id=charger.id,
                start_time=window_start,
                end_time=window_end,
                energy_added_kwh=energy_added,
            ))
            instance.book_charger(charger.id, window_start, window_end)
            return True

        return False


    def count_statutory_break_violations(self, instance) -> int:
        """Counts inter-trip breaks where continuous duty exceeded the max without
        a sufficient break at a stop with driver facilities."""
        violations = 0
        duty_start = None
        prev_end = None
        prev_stop = None

        for scheduled in self.scheduled_trips:
            trip = instance.get_trip(scheduled.trip_id)

            if duty_start is None:
                duty_start = scheduled.scheduled_start_time
            else:
                gap = scheduled.scheduled_start_time - prev_end
                duty_so_far = prev_end - duty_start

                if duty_so_far >= instance.max_continuous_duty_seconds:
                    has_facility = prev_stop in instance.stops_with_driver_facilities
                    long_enough = gap >= instance.min_statutory_break_seconds
                    if not (has_facility and long_enough):
                        violations += 1
                    duty_start = scheduled.scheduled_start_time  # reset after any break attempt

            prev_end = scheduled.scheduled_end_time
            prev_stop = trip.destination_stop

        return violations

    def line_change_penalty(self, instance) -> float:
        """Sum of line-change penalties (0-10 scale each) between consecutive trips."""
        total_penalty = 0.0
        prev_line_id = None
        for scheduled in self.scheduled_trips:
            trip = instance.get_trip(scheduled.trip_id)
            if prev_line_id is not None:
                total_penalty += instance.get_line_change_penalty(prev_line_id, trip.line_id)
            prev_line_id = trip.line_id
        return total_penalty

    def is_short_block(self, instance) -> bool:
        return len(self.scheduled_trips) < instance.short_block_trip_threshold

    def is_single_trip_block(self) -> bool:
        return len(self.scheduled_trips) == 1

    def vehicle_preference_penalty(self, instance) -> float:
        """Sum over trips of (1 - normalized preference score) for the assigned vehicle type."""
        total_penalty = 0.0
        for scheduled in self.scheduled_trips:
            trip = instance.get_trip(scheduled.trip_id)
            prefs = trip.vehicle_type_preference
            if not prefs:
                continue  # no preference stated — neutral, no penalty
            max_score = max(prefs.values())
            if max_score <= 0:
                continue
            assigned_score = prefs.get(self.vehicle_type, 0)
            total_penalty += 1.0 - (assigned_score / max_score)
        return total_penalty

    def total_shift_seconds(self, instance) -> float:
        total = 0.0
        for scheduled in self.scheduled_trips:
            trip = instance.get_trip(scheduled.trip_id)
            total += abs(scheduled.scheduled_start_time - trip.start_time)
        return total

    def total_max_shift_seconds(self, instance) -> float:
        total = 0.0
        for scheduled in self.scheduled_trips:
            trip = instance.get_trip(scheduled.trip_id)
            total += trip.max_shift_minutes * 60
        return total

    def duration_seconds(self) -> int:
        if not self.scheduled_trips:
            return 0
        first = self.scheduled_trips[0]
        last = self.scheduled_trips[-1]
        return last.scheduled_end_time - first.scheduled_start_time

    def meets_minimum_requirements(self, instance) -> bool:
        if len(self.scheduled_trips) < instance.min_block_trips:
            return False
        if self.duration_seconds() < instance.min_block_duration_seconds:
            return False
        return True

    def has_direction_violation(self, instance) -> bool:
        prev_trip = None
        for scheduled in self.scheduled_trips:
            trip = instance.get_trip(scheduled.trip_id)
            if prev_trip is not None:
                line = instance.get_line(trip.line_id)
                prev_line = instance.get_line(prev_trip.line_id)
                is_circular = (line and line.is_circular) or (prev_line and prev_line.is_circular)
                if not is_circular and prev_trip.direction and trip.direction:
                    if prev_trip.direction == trip.direction:
                        return True
            prev_trip = trip
        return False