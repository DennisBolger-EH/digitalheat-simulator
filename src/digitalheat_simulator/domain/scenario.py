"""Site-local scenario inputs with explicit interval boundaries and provenance."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite

from digitalheat_simulator.domain.parameters import Provenance
from digitalheat_simulator.domain.thermal import Rack


def _quantity(name: str, value: int, minimum: int = 0) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


def _nonnegative(name: str, value: float) -> None:
    if type(value) not in (int, float) or not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.utcoffset() is None or self.end.utcoffset() is None:
            raise ValueError("interval bounds must be timezone-aware")
        if self.end.astimezone(UTC) <= self.start.astimezone(UTC):
            raise ValueError("interval end must follow start")

    @property
    def duration_hours(self) -> float:
        return (self.end.astimezone(UTC) - self.start.astimezone(UTC)) / timedelta(hours=1)

    def key(self) -> tuple[datetime, datetime]:
        return self.start.astimezone(UTC), self.end.astimezone(UTC)


@dataclass(frozen=True)
class DemandPoint:
    interval: Interval
    energy_kwh: float

    def __post_init__(self) -> None:
        if not isinstance(self.interval, Interval):
            raise TypeError("demand interval must be an Interval")
        _nonnegative("demand energy_kwh", self.energy_kwh)


@dataclass(frozen=True)
class ThermalDemandSeries:
    identifier: str
    points: tuple[DemandPoint, ...]
    provenance: Provenance

    def __post_init__(self) -> None:
        if not isinstance(self.identifier, str) or not self.identifier.strip():
            raise ValueError("demand identifier must be nonempty")
        if not isinstance(self.provenance, Provenance):
            raise TypeError("demand provenance is required")
        if self.provenance.unit != "kWh":
            raise ValueError("demand provenance unit must be kWh")
        if not isinstance(self.points, tuple) or not self.points:
            raise ValueError("demand points must be a nonempty tuple")
        previous = None
        for point in self.points:
            if not isinstance(point, DemandPoint):
                raise TypeError("demand points must be DemandPoint instances")
            start, end = point.interval.key()
            if previous is not None and start != previous:
                raise ValueError("demand intervals must be contiguous and in elapsed-time order")
            previous = end


@dataclass(frozen=True)
class OperationPoint:
    interval: Interval
    on: bool

    def __post_init__(self) -> None:
        if not isinstance(self.interval, Interval) or type(self.on) is not bool:
            raise ValueError("operation requires an interval and boolean on state")


@dataclass(frozen=True)
class RackGroup:
    identifier: str
    rack: Rack
    quantity: int
    operation: tuple[OperationPoint, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.identifier, str) or not self.identifier.strip():
            raise ValueError("rack group identifier must be nonempty")
        if not isinstance(self.rack, Rack):
            raise TypeError("rack must be a Rack")
        _quantity("rack quantity", self.quantity)
        if not isinstance(self.operation, tuple) or not all(
            isinstance(point, OperationPoint) for point in self.operation
        ):
            raise ValueError("operation must be a tuple of OperationPoint")


@dataclass(frozen=True)
class SiteGroup:
    identifier: str
    consumer_kind: str
    quantity: int
    demand: ThermalDemandSeries
    racks: tuple[RackGroup, ...]
    storage_capacity_kwh: float
    initial_storage_kwh: float

    def __post_init__(self) -> None:
        for name in ("identifier", "consumer_kind"):
            item = getattr(self, name)
            if not isinstance(item, str) or not item.strip():
                raise ValueError(f"{name} must be nonempty")
        _quantity("site quantity", self.quantity, 1)
        if not isinstance(self.demand, ThermalDemandSeries):
            raise TypeError("site demand must be a ThermalDemandSeries")
        if not isinstance(self.racks, tuple) or not all(
            isinstance(r, RackGroup) for r in self.racks
        ):
            raise TypeError("racks must be a tuple of RackGroup")
        if len({r.identifier for r in self.racks}) != len(self.racks):
            raise ValueError("rack group identifiers must be unique within a site")
        _nonnegative("storage capacity kWh", self.storage_capacity_kwh)
        _nonnegative("initial storage kWh", self.initial_storage_kwh)
        if self.initial_storage_kwh > self.storage_capacity_kwh:
            raise ValueError("initial storage exceeds capacity")
        for rack in self.racks:
            if len(rack.operation) != len(self.demand.points):
                raise ValueError("operation and demand lengths must match")
            for operation, point in zip(rack.operation, self.demand.points, strict=True):
                if operation.interval.key() != point.interval.key():
                    raise ValueError("operation interval must match demand interval")


@dataclass(frozen=True)
class Scenario:
    sites: tuple[SiteGroup, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.sites, tuple) or not self.sites:
            raise ValueError("scenario must contain at least one site group")
        if not all(isinstance(site, SiteGroup) for site in self.sites):
            raise TypeError("scenario sites must be SiteGroup instances")
        if len({site.identifier for site in self.sites}) != len(self.sites):
            raise ValueError("site identifiers must be unique")
        reference = tuple(p.interval.key() for p in self.sites[0].demand.points)
        for site in self.sites[1:]:
            if tuple(p.interval.key() for p in site.demand.points) != reference:
                raise ValueError("site demand intervals must match")
