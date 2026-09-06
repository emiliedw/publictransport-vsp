from dataclasses import dataclass, field
from .trip import ScheduledTrip
from .charging_event import ChargingEvent
from .vehicle_type import VehicleType


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

    # ---- internal iteration helpers ----

    def _consecutive_scheduled_pairs(self):
        """Yield (current, next) for each pair of adjacent ScheduledTrips."""
        for i in range(len(self.scheduled_trips) - 1):
            yield self.scheduled_trips[i], self.scheduled_trips[i + 1]

    def _consecutive_trips(self, instance):
        """Yield (prev_trip, trip) for each pair of adjacent Trips (resolved from scheduled_trips)."""
        prev_trip = None
        for scheduled in self.scheduled_trips:
            trip = instance.get_trip(scheduled.trip_id)
            if prev_trip is not None:
                yield prev_trip, trip
            prev_trip = trip

    @staticmethod
    def _deadhead_consumption_kwh(instance, consumption_profile, prev_trip, trip, hour) -> float:
        if prev_trip is None or prev_trip.destination_stop == trip.origin_stop:
            return 0.0
        deadhead = instance.get_deadhead(prev_trip.destination_stop, trip.origin_stop)
        if deadhead is None:
            return 0.0
        rate = consumption_profile.consumption_kwh_per_km(hour=hour)
        return deadhead.distance_km * rate

    @staticmethod
    def _trip_consumption_kwh(consumption_profile, trip, hour) -> float:
        rate = consumption_profile.consumption_kwh_per_km(line_id=trip.line_id, hour=hour)
        return trip.distance_km * rate

    # ---- hard constraints ----

    def can_return_to_depot(self, instance) -> bool:
        """Hard constraint: a block must end at the same depot it started from."""
        if not self.scheduled_trips:
            return True

        depot = instance.get_depot(self.depot_id)
        if depot is None:
            return False

        last_trip = instance.get_trip(self.scheduled_trips[-1].trip_id)
        if last_trip.destination_stop == depot.location_stop_id:
            return True

        return instance.get_deadhead(last_trip.destination_stop, depot.location_stop_id) is not None

    def meets_minimum_requirements(self, instance) -> bool:
        if len(self.scheduled_trips) < instance.min_block_trips:
            return False
        if self.duration_seconds() < instance.min_block_duration_seconds:
            return False
        return True

    def has_direction_violation(self, instance) -> bool:
        for prev_trip, trip in self._consecutive_trips(instance):
            if not prev_trip.direction or not trip.direction:
                continue
            if prev_trip.direction != trip.direction:
                continue
            line = instance.get_line(trip.line_id)
            prev_line = instance.get_line(prev_trip.line_id)
            is_circular = (line and line.is_circular) or (prev_line and prev_line.is_circular)
            if not is_circular:
                return True
        return False

    # ---- basic metrics ----

    def duration_seconds(self) -> int:
        if not self.scheduled_trips:
            return 0
        return self.scheduled_trips[-1].scheduled_end_time - self.scheduled_trips[0].scheduled_start_time

    def is_short_block(self, instance) -> bool:
        return len(self.scheduled_trips) < instance.short_block_trip_threshold

    def is_single_trip_block(self) -> bool:
        return len(self.scheduled_trips) == 1

    def count_line_changes(self, instance) -> int:
        return sum(1 for prev, cur in self._consecutive_trips(instance) if prev.line_id != cur.line_id)

    # ---- energy / SoC ----

    def energy_consumed_kwh(self, instance, consumption_profile) -> float:
        total_kwh = 0.0
        prev_trip = None
        for scheduled in self.scheduled_trips:
            trip = instance.get_trip(scheduled.trip_id)
            hour = (instance.seconds_since_day_start(scheduled.scheduled_start_time) // 3600) % 24
            total_kwh += self._deadhead_consumption_kwh(instance, consumption_profile, prev_trip, trip, hour)
            total_kwh += self._trip_consumption_kwh(consumption_profile, trip, hour)
            prev_trip = trip
        return total_kwh

    def starting_soc_kwh(self, instance, params) -> float:
        """SoC at block start, after any overnight depot charging."""
        if params.battery_capacity_kwh is None:
            return 0.0
        if params.init_load_fraction is not None:
            return params.init_load_fraction * params.battery_capacity_kwh
        return params.battery_capacity_kwh  # no init_load specified — assume full charge

    def remaining_soc_kwh(self, instance, params) -> float:
        return self.starting_soc_kwh(instance, params) - self.energy_consumed_kwh(instance, params.consumption_profile)

    def try_charge_at_stop(self, instance, stop_id: str, window_start: int, window_end: int) -> bool:
        available_seconds = window_end - window_start
        if available_seconds <= 0:
            return False

        for charger in instance.get_chargers_at_location(stop_id):
            if not charger.is_available(window_start, window_end, instance.operating_day_start_seconds):
                continue
            if available_seconds < charger.min_charging_minutes * 60:
                continue
            if not instance.is_charger_free(charger.id, window_start, window_end):
                continue

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

    def overcharging_penalty_kwh(self, instance, params) -> float:
        """Soft-constraint penalty: sum of (SoC above ermax) at the start of each charging event."""
        if params.max_soc_before_charging_fraction is None or params.battery_capacity_kwh is None:
            return 0.0

        threshold_kwh = params.max_soc_before_charging_fraction * params.battery_capacity_kwh
        events_by_start = sorted(self.charging_events, key=lambda e: e.start_time)

        penalty = 0.0
        consumed_kwh = 0.0
        event_idx = 0

        def apply_pending_events(up_to_time) -> None:
            nonlocal event_idx, consumed_kwh, penalty
            while event_idx < len(events_by_start) and events_by_start[event_idx].start_time <= up_to_time:
                event = events_by_start[event_idx]
                remaining_soc = params.battery_capacity_kwh - consumed_kwh
                if remaining_soc > threshold_kwh:
                    penalty += remaining_soc - threshold_kwh
                consumed_kwh -= event.energy_added_kwh
                event_idx += 1

        prev_trip = None
        for scheduled in self.scheduled_trips:
            trip = instance.get_trip(scheduled.trip_id)
            hour = (instance.seconds_since_day_start(scheduled.scheduled_start_time) // 3600) % 24

            consumed_kwh += self._deadhead_consumption_kwh(instance, params.consumption_profile, prev_trip, trip, hour)
            apply_pending_events(scheduled.scheduled_start_time)
            consumed_kwh += self._trip_consumption_kwh(params.consumption_profile, trip, hour)

            prev_trip = trip

        apply_pending_events(float("inf"))
        return penalty

    # ---- soft-constraint penalties ----

    def statutory_break_penalty(self, instance) -> float:
        """Seconds of required statutory break not satisfied. 0.0 = fully compliant.
        Breaks may be split into segments >= min_break_component_seconds, each at a facility stop."""
        if not self.scheduled_trips:
            return 0.0

        duty_seconds = self.duration_seconds()
        required_break = 0
        for threshold_seconds, break_needed in sorted(instance.duty_break_thresholds):
            if duty_seconds > threshold_seconds:
                required_break = break_needed
        if required_break == 0:
            return 0.0

        qualifying_break = 0
        for current, nxt in self._consecutive_scheduled_pairs():
            gap = nxt.scheduled_start_time - current.scheduled_end_time
            prev_stop = instance.get_trip(current.trip_id).destination_stop
            if gap >= instance.min_break_component_seconds and prev_stop in instance.stops_with_driver_facilities:
                qualifying_break += gap

        return max(0, required_break - qualifying_break)

    def line_change_penalty(self, instance) -> float:
        """Sum of line-change penalties (0-10 scale each) between consecutive trips."""
        return sum(
            instance.get_line_change_penalty(prev.line_id, cur.line_id)
            for prev, cur in self._consecutive_trips(instance)
        )

    def line_change_count_excess(self, instance) -> int:
        if instance.max_line_changes_per_block is None:
            return 0
        return max(0, self.count_line_changes(instance) - instance.max_line_changes_per_block)

    def vehicle_preference_penalty(self, instance) -> float:
        """Sum over trips of (1 - score/10) for the assigned vehicle type, on a fixed 0-10 scale."""
        total_penalty = 0.0
        for scheduled in self.scheduled_trips:
            prefs = instance.get_trip(scheduled.trip_id).vehicle_type_preference
            if not prefs:
                continue
            score = prefs.get(self.vehicle_type, 0)
            total_penalty += 1.0 - (score / 10.0)
        return total_penalty

    def total_shift_seconds(self, instance) -> float:
        return sum(
            abs(scheduled.scheduled_start_time - instance.get_trip(scheduled.trip_id).start_time)
            for scheduled in self.scheduled_trips
        )

    def total_max_shift_seconds(self, instance) -> float:
        return sum(
            instance.get_trip(scheduled.trip_id).max_shift_minutes * 60
            for scheduled in self.scheduled_trips
        )

    def single_trip_break_excess_seconds(self, instance) -> int:
        """Sum of (break duration - pbmax) for any inter-trip break exceeding pbmax."""
        if instance.max_single_trip_break_seconds is None or len(self.scheduled_trips) < 2:
            return 0
        total_excess = 0
        for current, nxt in self._consecutive_scheduled_pairs():
            gap = nxt.scheduled_start_time - current.scheduled_end_time
            if gap > instance.max_single_trip_break_seconds:
                total_excess += gap - instance.max_single_trip_break_seconds
        return total_excess

    def long_break_depot_violation_seconds(self, instance) -> int:
        """Seconds of non-compliance with the depot-return policy for any break longer than br_max."""
        if instance.br_max_seconds is None or len(self.scheduled_trips) < 2:
            return 0

        home_depot = instance.get_depot(self.depot_id)
        total_violation = 0

        for current, nxt in self._consecutive_scheduled_pairs():
            gap = nxt.scheduled_start_time - current.scheduled_end_time
            if gap <= instance.br_max_seconds:
                continue

            break_stop = instance.get_trip(current.trip_id).destination_stop

            if instance.depot_return_policy == 1:
                compliant = home_depot is not None and break_stop == home_depot.location_stop_id
            elif instance.depot_return_policy == 2:
                compliant = instance.is_at_any_depot(break_stop)
            elif instance.depot_return_policy == 3:
                compliant = break_stop in instance.stops_with_secured_parking
            else:
                compliant = True

            if not compliant:
                total_violation += gap - instance.br_max_seconds

        return total_violation