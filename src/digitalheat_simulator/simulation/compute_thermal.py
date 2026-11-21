"""Translate physical rack execution into existing site-local thermal balances."""

from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from math import fsum, isfinite

from digitalheat_simulator.domain.compute import ComputeRack, Job, JobProgress
from digitalheat_simulator.domain.scenario import Scenario, SiteGroup
from digitalheat_simulator.simulation.scenario import (
    EnergyFlows,
    ScenarioResult,
    SiteResult,
    aggregate_scenario,
    energy_flows,
)
from digitalheat_simulator.workload.execution import (
    ExecutionSegment,
    union_seconds,
    validate_execution,
)

RackKey = tuple[str, str]


@dataclass(frozen=True)
class RackUsage:
    rack: ComputeRack
    on_seconds: float
    delivered_work_tflop: float
    period_seconds: float

    @property
    def period_utilization(self) -> float | None:
        capacity = self.rack.available_capacity_tflop_per_s * self.period_seconds
        return self.delivered_work_tflop / capacity if capacity else None

    @property
    def on_utilization(self) -> float | None:
        capacity = self.rack.available_capacity_tflop_per_s * self.on_seconds
        return self.delivered_work_tflop / capacity if capacity else None


@dataclass(frozen=True)
class IntegratedResult:
    progress: tuple[JobProgress, ...]
    thermal: ScenarioResult
    racks: tuple[RackUsage, ...]


@dataclass(frozen=True)
class RackOnInterval:
    """Observed physical-rack occupancy, independent of ideal compute progress."""

    rack: ComputeRack
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.rack, ComputeRack):
            raise TypeError("rack must be a ComputeRack")
        if self.start.utcoffset() is None or self.end.utcoffset() is None:
            raise ValueError("rack interval bounds must be timezone-aware")
        if self.end.astimezone(UTC) <= self.start.astimezone(UTC):
            raise ValueError("rack interval end must follow start")


def simulate_rack_intervals(
    scenario: Scenario, racks: tuple[ComputeRack, ...], intervals: tuple[RackOnInterval, ...]
) -> ScenarioResult:
    """Integrate observed occupancy without inventing ideal compute work."""
    validate_compute_sites(scenario, racks)
    points = scenario.sites[0].demand.points
    starts = [point.interval.start.astimezone(UTC) for point in points]
    final = points[-1].interval.end.astimezone(UTC)
    rack_map = {(rack.site_identifier, rack.identifier): rack for rack in racks}
    chunks: dict[tuple[int, RackKey], list[tuple[datetime, datetime]]] = defaultdict(list)
    for interval in intervals:
        key = (interval.rack.site_identifier, interval.rack.identifier)
        if rack_map.get(key) != interval.rack:
            raise ValueError("rack interval references an unknown or mismatched rack")
        start, end = interval.start.astimezone(UTC), interval.end.astimezone(UTC)
        if start < starts[0] or end > final:
            raise ValueError("rack interval extends outside the simulation horizon")
        index = bisect_right(starts, start) - 1
        while start < end:
            stop = min(end, points[index].interval.end.astimezone(UTC))
            chunks[index, key].append((start, stop))
            start = stop
            index += 1
    by_site: dict[tuple[str, int], list[tuple[ComputeRack, float]]] = defaultdict(list)
    for (index, key), spans in chunks.items():
        by_site[key[0], index].append((rack_map[key], union_seconds(spans)))
    results = []
    for site in scenario.sites:
        opening = site.initial_storage_kwh
        flows = []
        for index in range(len(points)):
            flow = execution_interval_flows(
                site, index, opening, tuple(by_site[site.identifier, index])
            )
            flows.append(flow)
            opening = flow.storage_closing_kwh
        results.append(SiteResult(site, tuple(flows)))
    return aggregate_scenario(scenario, tuple(results))


def validate_compute_sites(scenario: Scenario, racks: tuple[ComputeRack, ...]) -> None:
    """Require one explicit site per group and an exact physical-rack inventory."""
    sites = {site.identifier: site for site in scenario.sites}
    if any(site.quantity != 1 for site in scenario.sites):
        raise ValueError("compute scheduling requires individually identified sites")
    if any(
        point.on for site in scenario.sites for group in site.racks for point in group.operation
    ):
        raise ValueError("compute-driven scenarios require explicit rack operations to be off")
    if len({(rack.site_identifier, rack.identifier) for rack in racks}) != len(racks):
        raise ValueError("site-local rack identifiers must be unique")
    actual: dict[str, Counter] = {identifier: Counter() for identifier in sites}
    for rack in racks:
        if rack.site_identifier not in sites:
            raise ValueError(f"unknown rack site: {rack.site_identifier}")
        actual[rack.site_identifier][rack.thermal] += 1
    for site in scenario.sites:
        expected = Counter()
        for group in site.racks:
            expected[group.rack] += group.quantity
        if actual[site.identifier] != expected:
            raise ValueError(f"compute rack inventory does not match site {site.identifier}")


def execution_interval_flows(
    site: SiteGroup,
    index: int,
    opening_kwh: float,
    rack_seconds: tuple[tuple[ComputeRack, float], ...],
) -> EnergyFlows:
    """Balance one site's interval using unioned ON seconds for each physical rack."""
    point = site.demand.points[index]
    duration = point.interval.duration_hours * 3600
    seen: set[RackKey] = set()
    for rack, seconds in rack_seconds:
        key = (rack.site_identifier, rack.identifier)
        if rack.site_identifier != site.identifier or key in seen:
            raise ValueError("rack ON times must identify distinct racks at the same site")
        seen.add(key)
        if not isfinite(seconds) or seconds < 0 or seconds > duration + 1e-9:
            raise ValueError("rack ON time must fit within the thermal interval")
    electrical = fsum(
        rack.thermal.electrical_power_kw * seconds / 3600 for rack, seconds in rack_seconds
    )
    gross = fsum(rack.thermal.thermal_power_kw * seconds / 3600 for rack, seconds in rack_seconds)
    recovered = fsum(
        rack.thermal.thermal_power_kw * rack.thermal.recovery_efficiency * seconds / 3600
        for rack, seconds in rack_seconds
    )
    unrecovered = fsum(
        rack.thermal.thermal_power_kw * (1 - rack.thermal.recovery_efficiency) * seconds / 3600
        for rack, seconds in rack_seconds
    )
    return energy_flows(
        point.energy_kwh,
        electrical,
        gross,
        recovered,
        unrecovered,
        site.storage_capacity_kwh,
        opening_kwh,
    )


def simulate_execution(
    scenario: Scenario,
    jobs: tuple[Job, ...],
    racks: tuple[ComputeRack, ...],
    segments: tuple[ExecutionSegment, ...],
) -> IntegratedResult:
    """Validate execution and integrate physical rack ON unions into local balances."""
    validate_compute_sites(scenario, racks)
    points = scenario.sites[0].demand.points
    starts = [point.interval.start.astimezone(UTC) for point in points]
    final = points[-1].interval.end.astimezone(UTC)
    progress = validate_execution(jobs, racks, segments, horizon=final)
    chunks: dict[tuple[int, RackKey], list[tuple[datetime, datetime]]] = defaultdict(list)
    for segment in segments:
        start, end = segment.start.astimezone(UTC), segment.end.astimezone(UTC)
        if start < starts[0] or end > final:
            raise ValueError("execution segment extends outside the simulation horizon")
        index = bisect_right(starts, start) - 1
        key = (segment.rack.site_identifier, segment.rack.identifier)
        while start < end:
            stop = min(end, points[index].interval.end.astimezone(UTC))
            chunks[index, key].append((start, stop))
            start = stop
            index += 1
    rack_map = {(rack.site_identifier, rack.identifier): rack for rack in racks}
    on_by_site_interval: dict[tuple[str, int], list[tuple[ComputeRack, float]]] = defaultdict(list)
    rack_on: dict[RackKey, list[float]] = defaultdict(list)
    for (index, key), intervals in chunks.items():
        seconds = union_seconds(intervals)
        on_by_site_interval[key[0], index].append((rack_map[key], seconds))
        rack_on[key].append(seconds)
    rack_work: dict[RackKey, list[float]] = defaultdict(list)
    for segment in segments:
        rack_work[segment.rack.site_identifier, segment.rack.identifier].append(
            segment.delivered_work_tflop
        )
    results = []
    for site in scenario.sites:
        opening = site.initial_storage_kwh
        flows = []
        for index in range(len(points)):
            result = execution_interval_flows(
                site, index, opening, tuple(on_by_site_interval[site.identifier, index])
            )
            flows.append(result)
            opening = result.storage_closing_kwh
        results.append(SiteResult(site, tuple(flows)))
    duration = (final - starts[0]).total_seconds()
    usage = tuple(
        RackUsage(
            rack,
            fsum(rack_on[rack.site_identifier, rack.identifier]),
            fsum(rack_work[rack.site_identifier, rack.identifier]),
            duration,
        )
        for rack in racks
    )
    return IntegratedResult(progress, aggregate_scenario(scenario, tuple(results)), usage)
