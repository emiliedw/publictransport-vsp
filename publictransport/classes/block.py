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

    def _consecutive_scheduled_pairs(self):
        for i in range(len(self.scheduled_trips) - 1):
            yield self.scheduled_trips[i], self.scheduled_trips[i + 1]

    def _consecutive_trips(self, instance):
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
        return self.duration_seconds() >= instance.min_block_duration_seconds

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

    # ---- reporting metrics ----

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

    def total_shift_seconds(self, instance) -> float:
        return sum(
            abs(scheduled.scheduled_start_time - instance.get_trip(scheduled.trip_id).start_time)
            for scheduled in self.scheduled_trips
        )

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
        if params.battery_capacity_kwh is None:
            return 0.0
        if params.init_load_fraction is not None:
            return params.init_load_fraction * params.battery_capacity_kwh
        return params.battery_capacity_kwh

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