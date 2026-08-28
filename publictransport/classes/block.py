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
        """Total energy used so far: all scheduled trips' distances + any deadheads between them."""
        total_kwh = 0.0
        prev_trip = None

        for scheduled in self.scheduled_trips:
            trip = instance.get_trip(scheduled.trip_id)
            hour = (scheduled.scheduled_start_time // 3600) % 24

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
        """Attempt to charge during an idle window at a stop. Returns True if a charge was inserted."""
        available_seconds = window_end - window_start
        if available_seconds <= 0:
            return False

        for charger in instance.get_chargers_at_location(stop_id):
            min_needed_seconds = charger.min_charging_minutes * 60
            if available_seconds < min_needed_seconds:
                continue  # not enough time at this charger — charging is not initiated

            energy_added = (available_seconds / 3600) * charger.charging_rate_kw
            self.add_charging_event(ChargingEvent(
                vehicle_id=self.vehicle_id,
                charger_id=charger.id,
                start_time=window_start,
                end_time=window_end,
                energy_added_kwh=energy_added,
            ))
            return True

        return False  # no charger here met the minimum-time requirement