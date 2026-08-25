from dataclasses import dataclass, field
from typing import Optional

from .classes.depot import Depot
from .classes.line import Line
from .classes.trip import Trip
from .classes.vehicle import Vehicle
from .classes.charger import Charger
from .classes.deadhead_trip import DeadheadTrip


@dataclass
class ProblemInstance:
    depots: dict[str, Depot]= field(default_factory=dict)
    lines: dict[str, Line]= field(default_factory=dict)
    trips: dict[str, Trip]= field(default_factory=dict)
    vehicles: dict[str, Vehicle]= field(default_factory=dict)
    chargers: dict[str, Charger]= field(default_factory=dict)

    #deadhead[(origin_stop, destination_stop)] -> DeadheadTrip
    deadheads: dict[tuple[str, str], DeadheadTrip] = field(default_factory=dict)

    def add_depot(self, depot: Depot) -> None:
        self.depots[depot.id]= depot

    def add_line(self, line: Line) -> None:
        self.lines[line.id]= line

    def add_trip(self, trip: Trip) -> None:
        self.trips[trip.id]= trip

    def add_vehicle(self, vehicle: Vehicle) -> None:
        self.vehicles[vehicle.id]= vehicle

    def add_charger(self, charger: Charger) -> None:
        self.chargers[charger.id]= charger

    def add_deadhead(self, deadhead: DeadheadTrip) -> None:
        self.deadheads[(deadhead.origin_stop, deadhead.destination_stop)]= deadhead



#GETTERS
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

#SORTERS

    def get_trips_sorted_by_start_time(self) -> list[Trip]:
        return sorted(self.trips.values(), key=lambda trip: trip.start_time)

    def get_trips_sorted_by_end_time(self) -> list[Trip]:
        return sorted(self.trips.values(), key=lambda trip: trip.end_time)