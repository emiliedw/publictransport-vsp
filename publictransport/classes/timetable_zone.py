from dataclasses import dataclass


@dataclass(frozen=True)
class TimetableZoneBoundary:
    #A single boundary time (seconds since day start) where the zone changes.
    boundary_time: int
    zone_before: str   #off peak or peak
    zone_after: str

@dataclass
class TimetableZones:
    """Sorted boundary times (seconds since day start) separating peak/off-peak zones."""
    boundaries: list[int]   # e.g. [0, 21600, 32400, 57600, 68400, 86400] for a day with 2 peak windows

    def zone_index(self, time_seconds: int) -> int:
        """Which zone segment this time falls into, as an index into the boundaries list."""
        for i in range(len(self.boundaries) - 1):
            if self.boundaries[i] <= time_seconds < self.boundaries[i + 1]:
                return i
        return len(self.boundaries) - 2  # fallback: last segment

    def max_shift_without_crossing(self, time_seconds: int) -> tuple[int, int]:
        """Returns (max_earlier_shift, max_later_shift) in seconds before hitting a zone boundary."""
        idx = self.zone_index(time_seconds)
        lower_bound = self.boundaries[idx]
        upper_bound = self.boundaries[idx + 1]
        max_earlier = time_seconds - lower_bound
        max_later = upper_bound - time_seconds
        return max_earlier, max_later