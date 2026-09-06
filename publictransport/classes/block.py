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


    def statutory_break_penalty(self, instance) -> float:
        """Soft-constraint penalty: seconds of required statutory break not satisfied.
        0.0 means fully compliant. Breaks may be split into segments >= min_break_component_seconds,
        each of which must occur at a stop with driver facilities."""
        if not self.scheduled_trips:
            return 0.0

        duty_seconds = self.duration_seconds()

        required_break = 0
        for threshold_seconds, break_needed in sorted(instance.duty_break_thresholds):
            if duty_seconds > threshold_seconds:
                required_break = break_needed
        if required_break == 0:
            return 0.0  # duty under the lowest threshold — no break required

        qualifying_break = 0
        prev_end = None
        prev_stop = None
        for scheduled in self.scheduled_trips:
            trip = instance.get_trip(scheduled.trip_id)
            if prev_end is not None:
                gap = scheduled.scheduled_start_time - prev_end
                if gap >= instance.min_break_component_seconds and prev_stop in instance.stops_with_driver_facilities:
                    qualifying_break += gap
            prev_end = scheduled.scheduled_end_time
            prev_stop = trip.destination_stop

        return max(0, required_break - qualifying_break)

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
        """Sum over trips of (1 - score/10) for the assigned vehicle type, on a fixed 0-10 scale."""
        total_penalty = 0.0
        for scheduled in self.scheduled_trips:
            trip = instance.get_trip(scheduled.trip_id)
            prefs = trip.vehicle_type_preference
            if not prefs:
                continue
            score = prefs.get(self.vehicle_type, 0)
            total_penalty += 1.0 - (score / 10.0)
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

    def overcharging_penalty_kwh(self, instance, params) -> float:
        """Soft-constraint penalty: sum of (SoC above ermax) at the start of each charging event."""
        if params.max_soc_before_charging_fraction is None or params.battery_capacity_kwh is None:
            return 0.0

        threshold_kwh = params.max_soc_before_charging_fraction * params.battery_capacity_kwh
        penalty = 0.0
        consumed_kwh = 0.0
        prev_trip = None

        events_by_start = sorted(self.charging_events, key=lambda e: e.start_time)
        event_idx = 0

        for scheduled in self.scheduled_trips:
            trip = instance.get_trip(scheduled.trip_id)
            hour = (instance.seconds_since_day_start(scheduled.scheduled_start_time) // 3600) % 24

            if prev_trip is not None and prev_trip.destination_stop != trip.origin_stop:
                deadhead = instance.get_deadhead(prev_trip.destination_stop, trip.origin_stop)
                if deadhead is not None:
                    rate = params.consumption_profile.consumption_kwh_per_km(hour=hour)
                    consumed_kwh += deadhead.distance_km * rate

            # any charging events that occur before this trip starts, in order
            while event_idx < len(events_by_start) and events_by_start[event_idx].start_time <= scheduled.scheduled_start_time:
                event = events_by_start[event_idx]
                remaining_soc = params.battery_capacity_kwh - consumed_kwh
                if remaining_soc > threshold_kwh:
                    penalty += remaining_soc - threshold_kwh
                consumed_kwh -= event.energy_added_kwh  # charging reduces "consumed" (tops the battery back up)
                event_idx += 1

            rate = params.consumption_profile.consumption_kwh_per_km(line_id=trip.line_id, hour=hour)
            consumed_kwh += trip.distance_km * rate
            prev_trip = trip

        # any remaining charging events after the last trip
        while event_idx < len(events_by_start):
            event = events_by_start[event_idx]
            remaining_soc = params.battery_capacity_kwh - consumed_kwh
            if remaining_soc > threshold_kwh:
                penalty += remaining_soc - threshold_kwh
            consumed_kwh -= event.energy_added_kwh
            event_idx += 1

        return penalty

    def line_change_count_excess(self, instance) -> int:
        """Soft-constraint penalty: how many line changes exceed lzmax, if set."""
        if instance.max_line_changes_per_block is None:
            return 0
        actual = self.count_line_changes(instance)
        return max(0, actual - instance.max_line_changes_per_block)

    def single_trip_break_excess_seconds(self, instance) -> int:
        """Soft-constraint penalty: sum of (break duration - pbmax) for any break immediately
        before or after a trip, where that break exceeds pbmax."""
        if instance.max_single_trip_break_seconds is None or len(self.scheduled_trips) < 2:
            return 0

        total_excess = 0
        for i in range(len(self.scheduled_trips) - 1):
            current_end = self.scheduled_trips[i].scheduled_end_time
            next_start = self.scheduled_trips[i + 1].scheduled_start_time
            gap = next_start - current_end
            if gap > instance.max_single_trip_break_seconds:
                total_excess += gap - instance.max_single_trip_break_seconds

        return total_excess

    def long_break_depot_violation_seconds(self, instance) -> int:
        """Soft-constraint penalty: for any break longer than br_max, seconds of non-compliance
        with the configured depot-return policy (1=home, 2=nearest/any depot, 3=secured terminus)."""
        if instance.br_max_seconds is None or len(self.scheduled_trips) < 2:
            return 0

        home_depot = instance.get_depot(self.depot_id)
        total_violation = 0

        for i in range(len(self.scheduled_trips) - 1):
            current = self.scheduled_trips[i]
            next_trip_sched = self.scheduled_trips[i + 1]
            gap = next_trip_sched.scheduled_start_time - current.scheduled_end_time

            if gap <= instance.br_max_seconds:
                continue  # break not long enough to trigger the rule

            trip_before = instance.get_trip(current.trip_id)
            break_stop = trip_before.destination_stop

            if instance.depot_return_policy == 1:
                compliant = home_depot is not None and break_stop == home_depot.location_stop_id
            elif instance.depot_return_policy == 2:
                compliant = instance.is_at_any_depot(break_stop)
            elif instance.depot_return_policy == 3:
                compliant = break_stop in instance.stops_with_secured_parking
            else:
                compliant = True  # unrecognized policy — don't penalize

            if not compliant:
                total_violation += gap - instance.br_max_seconds

        return total_violation

    def starting_soc_kwh(self, instance, params) -> float:
        """SoC at block start, after any overnight depot charging (constraint 30)."""
        if params.battery_capacity_kwh is None:
            return 0.0
        if params.init_load_fraction is not None:
            return params.init_load_fraction * params.battery_capacity_kwh
        return params.battery_capacity_kwh  # no init_load specified — assume full charge, as before

    def remaining_soc_kwh(self, instance, params) -> float:
        return self.starting_soc_kwh(instance, params) - self.energy_consumed_kwh(instance, params.consumption_profile)