"""Timezone-aware intervals with elapsed-time resolution."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class TimeGrid:
    start: datetime
    end: datetime
    resolution: timedelta = timedelta(hours=1)
    timezone: str = "Europe/Zurich"

    def __post_init__(self) -> None:
        if self.start.utcoffset() is None or self.end.utcoffset() is None:
            raise ValueError("Time grid boundaries must be timezone-aware")
        if self.resolution <= timedelta(0):
            raise ValueError("Time resolution must be positive")
        duration = self.end.astimezone(UTC) - self.start.astimezone(UTC)
        if duration <= timedelta(0) or duration % self.resolution != timedelta(0):
            raise ValueError("Time range must be positive and divisible by the resolution")
        ZoneInfo(self.timezone)

    def instants(self) -> tuple[datetime, ...]:
        """Return half-open interval starts in the display timezone."""
        current = self.start.astimezone(UTC)
        end = self.end.astimezone(UTC)
        zone = ZoneInfo(self.timezone)
        result = []
        while current < end:
            result.append(current.astimezone(zone))
            current += self.resolution
        return tuple(result)
