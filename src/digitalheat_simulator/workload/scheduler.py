"""Deterministic heat-aware reference scheduler for ideal compute jobs."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from heapq import heappop, heappush
from itertools import islice
from math import floor, fsum

from digitalheat_simulator.domain.compute import (
    WORK_ABS_TOL_TFLOP,
    WORK_REL_TOL,
    ComputeRack,
    Job,
    JobProgress,
)
from digitalheat_simulator.domain.scenario import Scenario
from digitalheat_simulator.simulation.compute_thermal import (
    IntegratedResult,
    execution_interval_flows,
    simulate_execution,
    validate_compute_sites,
)
from digitalheat_simulator.workload.execution import (
    ExecutionSegment,
    on_pause_step,
    validate_execution,
)


@dataclass(frozen=True)
class JobOutcome:
    progress: JobProgress
    completion: datetime | None
    deadline_missed: bool


@dataclass(frozen=True)
class ScheduleResult:
    segments: tuple[ExecutionSegment, ...]
    outcomes: tuple[JobOutcome, ...]
    integrated: IntegratedResult


@dataclass
class _State:
    job: Job
    completed: float = 0.0
    rack: ComputeRack | None = None
    active: bool = False
    completion: datetime | None = None

    @property
    def remaining(self) -> float:
        return max(0.0, self.job.required_work_tflop - self.completed)


@dataclass
class _Reservations:
    now: datetime
    end: datetime
    heat: dict[str, float]
    selected: dict[str, _State]
    load: dict[tuple[str, str], float]
    rack_seconds: dict[tuple[str, str], float]
    stop_at: dict[str, datetime]

    def reserve(self, state: _State, rack: ComputeRack, until: datetime) -> None:
        key = _key(rack)
        seconds = (min(self.end, until) - self.now).total_seconds()
        old = self.rack_seconds.get(key, 0.0)
        if seconds > old:
            self.heat[rack.site_identifier] += (seconds - old) * _heat_per_second(rack)
            self.rack_seconds[key] = seconds
        self.load[key] = self.load.get(key, 0.0) + state.job.requested_rate_tflop_per_s
        self.selected[state.job.identifier] = state
        state.rack = rack
        self.stop_at[state.job.identifier] = until


def _at_step(state: _State) -> bool:
    return on_pause_step(state.job, state.completed)


def _next_pause_work(state: _State) -> float:
    step = state.job.pause_step_tflop
    if not step or not state.job.interruptible:
        return state.remaining
    nearest = round(state.completed / step)
    if _at_step(state):
        target = (nearest + 1) * step
    else:
        target = (floor(state.completed / step) + 1) * step
    return min(state.remaining, target - state.completed)


def _duration(work: float, rate: float) -> timedelta:
    duration = timedelta(seconds=work / rate)
    delivered = duration.total_seconds() * rate
    tolerance = min(WORK_ABS_TOL_TFLOP + WORK_REL_TOL * work, work * 1e-7)
    if duration <= timedelta(0) or abs(work - delivered) > tolerance:
        raise ValueError("execution or pause point is not representable at microsecond resolution")
    return duration


def _key(rack: ComputeRack) -> tuple[str, str]:
    return rack.site_identifier, rack.identifier


def _heat_per_second(rack: ComputeRack) -> float:
    return rack.thermal.thermal_power_kw * rack.thermal.recovery_efficiency / 3600


def _project_finish(
    target: _State,
    now: datetime,
    racks: tuple[ComputeRack, ...],
    reservations: _Reservations,
    candidate: tuple[_State, ComputeRack, datetime] | None,
) -> datetime | None:
    """Project a job against currently uninterruptible rack commitments only."""
    release = max(now, target.job.release.astimezone(UTC))
    best: datetime | None = None
    for rack in racks:
        if rack.site_identifier not in target.job.eligible_sites:
            continue
        if target.rack is not None and rack != target.rack:
            continue
        if target.job.requested_rate_tflop_per_s > rack.available_capacity_tflop_per_s:
            continue
        blockers: list[tuple[datetime, float]] = []
        for state in reservations.selected.values():
            if state.rack != rack:
                continue
            if not state.job.interruptible or state.job.pause_step_tflop:
                stop = reservations.stop_at[state.job.identifier]
                if stop > release:
                    blockers.append((stop, state.job.requested_rate_tflop_per_s))
        if candidate is not None:
            state, candidate_rack, stop = candidate
            if candidate_rack == rack and stop > release:
                blockers.append((stop, state.job.requested_rate_tflop_per_s))
        load = fsum(rate for _, rate in blockers)
        start = release
        for stop, rate in sorted(blockers):
            if load + target.job.requested_rate_tflop_per_s <= rack.available_capacity_tflop_per_s:
                break
            start = stop
            load -= rate
        if load + target.job.requested_rate_tflop_per_s > rack.available_capacity_tflop_per_s:
            continue
        finish = start + _duration(target.remaining, target.job.requested_rate_tflop_per_s)
        if best is None or finish < best:
            best = finish
    return best


def _new_deadline_conflicts(
    state: _State,
    rack: ComputeRack,
    until: datetime,
    now: datetime,
    future: list[_State],
    racks: tuple[ComputeRack, ...],
    reservations: _Reservations,
) -> tuple[int, int]:
    if state.job.interruptible and not state.job.pause_step_tflop:
        return 0, 0
    earlier_conflicts = 0
    total_conflicts = 0
    for target in future:
        if target is state or target.job.identifier in reservations.selected:
            continue
        if target.job.release.astimezone(UTC) >= until:
            continue
        baseline = _project_finish(target, now, racks, reservations, None)
        deadline = target.job.deadline.astimezone(UTC)
        if baseline is None or baseline > deadline:
            continue
        projected = _project_finish(target, now, racks, reservations, (state, rack, until))
        if projected is None or projected > deadline:
            total_conflicts += 1
            if (deadline, target.job.identifier) < (
                state.job.deadline.astimezone(UTC),
                state.job.identifier,
            ):
                earlier_conflicts += 1
    return earlier_conflicts, total_conflicts


def _latest_start(
    state: _State,
    rack: ComputeRack,
    available: list[_State],
    racks: tuple[ComputeRack, ...],
    reservations: _Reservations,
) -> datetime:
    """Estimate deadline slack using a greedy, heat-independent EDF projection."""
    now = reservations.now
    duration = _duration(state.remaining, state.job.requested_rate_tflop_per_s)
    if len(available) == 1 and not reservations.selected:
        return state.job.deadline.astimezone(UTC) - duration
    ready: list[tuple[_State, tuple[ComputeRack, ...]]] = [(state, (rack,))]
    own_priority = (state.job.deadline.astimezone(UTC), state.job.identifier)
    for other in available:
        if other is state or other.job.identifier in reservations.selected:
            continue
        if (other.job.deadline.astimezone(UTC), other.job.identifier) <= own_priority:
            continue
        possible = tuple(
            item
            for item in racks
            if item.site_identifier in other.job.eligible_sites
            and (other.rack is None or other.rack == item)
            and other.job.requested_rate_tflop_per_s <= item.available_capacity_tflop_per_s
        )
        if possible:
            ready.append((other, possible))
    running: list[tuple[datetime, str, tuple[str, str], float]] = []
    load: dict[tuple[str, str], float] = {}
    for selected in reservations.selected.values():
        if selected.rack is None:
            raise RuntimeError("selected job has no rack")
        key = _key(selected.rack)
        rate = selected.job.requested_rate_tflop_per_s
        finish = now + _duration(selected.remaining, rate)
        heappush(running, (finish, selected.job.identifier, key, rate))
        load[key] = load.get(key, 0.0) + rate
    latest = state.job.deadline.astimezone(UTC)
    current = now
    while ready or running:
        remaining = []
        for item, possible in ready:
            rate = item.job.requested_rate_tflop_per_s
            choices = [
                (
                    candidate.available_capacity_tflop_per_s
                    - load.get(_key(candidate), 0.0)
                    - rate,
                    _key(candidate),
                )
                for candidate in possible
                if load.get(_key(candidate), 0.0) + rate <= candidate.available_capacity_tflop_per_s
            ]
            if not choices:
                remaining.append((item, possible))
                continue
            _, key = min(choices)
            finish = current + _duration(item.remaining, rate)
            latest = min(latest, now + (item.job.deadline.astimezone(UTC) - finish))
            heappush(running, (finish, item.job.identifier, key, rate))
            load[key] = load.get(key, 0.0) + rate
        ready = remaining
        if not running:
            raise RuntimeError("deadline projection cannot place an eligible job")
        current, _, key, rate = heappop(running)
        load[key] -= rate
        while running and running[0][0] == current:
            _, _, key, rate = heappop(running)
            load[key] -= rate
    return latest


def _future_latest_start(
    state: _State,
    rack: ComputeRack,
    latest: datetime,
    pending: list[_State],
    cursor: int,
    racks: tuple[ComputeRack, ...],
) -> datetime:
    """Reserve time for individually feasible future work pinned to this rack."""
    own_duration = _duration(state.remaining, state.job.requested_rate_tflop_per_s)
    for target in islice(pending, cursor, None):
        release = target.job.release.astimezone(UTC)
        if release >= state.job.deadline.astimezone(UTC):
            break
        if rack.site_identifier not in target.job.eligible_sites:
            continue
        if (
            target.job.requested_rate_tflop_per_s + state.job.requested_rate_tflop_per_s
            <= rack.available_capacity_tflop_per_s
        ):
            continue
        possible = [
            item
            for item in racks
            if item.site_identifier in target.job.eligible_sites
            and target.job.requested_rate_tflop_per_s <= item.available_capacity_tflop_per_s
        ]
        if len(possible) != 1 or possible[0] != rack:
            continue
        target_duration = _duration(target.remaining, target.job.requested_rate_tflop_per_s)
        target_latest = target.job.deadline.astimezone(UTC) - target_duration
        if target_latest >= release:
            latest = min(latest, target_latest - own_duration)
    return latest


def schedule(
    scenario: Scenario, jobs: tuple[Job, ...], racks: tuple[ComputeRack, ...]
) -> ScheduleResult:
    """Schedule fixed-rate work against local interval heat budgets.

    Deadline estimates use a greedy projection of released work and known
    uninterruptible commitments; they are not a global feasibility guarantee.
    """
    validate_compute_sites(scenario, racks)
    validate_execution(jobs, racks, ())
    states = [_State(job) for job in jobs]
    pending = sorted(states, key=lambda s: (s.job.release.astimezone(UTC), s.job.identifier))
    available: list[_State] = []
    racks = tuple(sorted(racks, key=_key))
    opening = {site.identifier: site.initial_storage_kwh for site in scenario.sites}
    segments: list[ExecutionSegment] = []
    cursor = 0
    reference = scenario.sites[0].demand.points

    for index, point in enumerate(reference):
        now = point.interval.start.astimezone(UTC)
        end = point.interval.end.astimezone(UTC)
        used_heat = {site.identifier: 0.0 for site in scenario.sites}
        on_seconds: dict[tuple[str, str], float] = {}
        budgets = {
            site.identifier: site.demand.points[index].energy_kwh
            + site.storage_capacity_kwh
            - opening[site.identifier]
            for site in scenario.sites
        }
        while now < end:
            while cursor < len(pending) and pending[cursor].job.release.astimezone(UTC) <= now:
                available.append(pending[cursor])
                cursor += 1
            available = [state for state in available if state.completion is None]
            available.sort(key=lambda s: (s.job.deadline.astimezone(UTC), s.job.identifier))
            reservations = _Reservations(now, end, dict(used_heat), {}, {}, {}, {})
            wake_times: list[datetime] = []

            # Running work that cannot currently pause holds its rack before new admissions.
            for state in available:
                if state.active and (not state.job.interruptible or not _at_step(state)):
                    if state.rack is None:
                        raise RuntimeError("active job has no rack")
                    until = now + _duration(
                        _next_pause_work(state), state.job.requested_rate_tflop_per_s
                    )
                    reservations.reserve(state, state.rack, until)

            for state in available:
                if state.job.identifier in reservations.selected:
                    continue
                job = state.job
                quantum = _next_pause_work(state)
                wanted = now + _duration(quantum, job.requested_rate_tflop_per_s)
                future = []
                if not job.interruptible or job.pause_step_tflop:
                    future.extend(available)
                    for target in islice(pending, cursor, None):
                        if target.job.release.astimezone(UTC) >= wanted:
                            break
                        future.append(target)
                choices = []
                for rack in racks:
                    key = _key(rack)
                    if rack.site_identifier not in job.eligible_sites:
                        continue
                    if state.rack is not None and rack != state.rack:
                        continue
                    if (
                        reservations.load.get(key, 0.0) + job.requested_rate_tflop_per_s
                        > rack.available_capacity_tflop_per_s
                    ):
                        continue
                    latest = _latest_start(state, rack, available, racks, reservations)
                    latest = _future_latest_start(state, rack, latest, pending, cursor, racks)
                    if latest > now:
                        wake_times.append(latest)
                    urgent = now >= latest
                    seconds = (min(end, wanted) - now).total_seconds()
                    existing = reservations.rack_seconds.get(key, 0.0)
                    heat_rate = _heat_per_second(rack)
                    incremental = max(0.0, seconds - existing) * heat_rate
                    opportunity = max(
                        0.0, budgets[rack.site_identifier] - reservations.heat[rack.site_identifier]
                    )
                    dumped = max(0.0, incremental - opportunity)
                    earlier_conflicts, conflicts = _new_deadline_conflicts(
                        state, rack, wanted, now, future, racks, reservations
                    )
                    choices.append(
                        (
                            earlier_conflicts,
                            latest < now,
                            conflicts,
                            dumped,
                            -opportunity,
                            key,
                            rack,
                            wanted,
                            incremental,
                            opportunity,
                            urgent,
                        )
                    )
                if not choices:
                    continue
                (
                    earlier_conflicts,
                    _,
                    conflicts,
                    _,
                    _,
                    _,
                    rack,
                    wanted,
                    incremental,
                    opportunity,
                    urgent,
                ) = min(choices)
                if earlier_conflicts or (conflicts and not urgent):
                    continue
                heat_rate = _heat_per_second(rack)
                if not urgent and incremental > opportunity + 1e-12:
                    if job.interruptible and job.pause_step_tflop:
                        continue
                    if not job.interruptible:
                        if opportunity <= 1e-12:
                            continue
                    elif heat_rate:
                        allowable = (
                            reservations.rack_seconds.get(_key(rack), 0.0) + opportunity / heat_rate
                        )
                        wanted = min(wanted, now + timedelta(seconds=allowable))
                        if wanted <= now:
                            continue
                reservations.reserve(state, rack, wanted)

            next_time = end
            if cursor < len(pending):
                next_time = min(next_time, pending[cursor].job.release.astimezone(UTC))
            if wake_times:
                next_time = min(next_time, min(wake_times))
            for state in reservations.selected.values():
                next_time = min(next_time, reservations.stop_at[state.job.identifier])
            for state in available:
                if state.job.identifier not in reservations.selected:
                    latest = state.job.deadline.astimezone(UTC) - _duration(
                        state.remaining, state.job.requested_rate_tflop_per_s
                    )
                    if latest > now:
                        next_time = min(next_time, latest)
            if next_time <= now:
                raise RuntimeError("scheduler failed to advance time")
            seconds = (next_time - now).total_seconds()
            active_racks: dict[tuple[str, str], ComputeRack] = {}
            for state in available:
                state.active = state.job.identifier in reservations.selected
                if not state.active:
                    continue
                rack = state.rack
                if rack is None:
                    raise RuntimeError("active job has no rack")
                finishes = next_time >= now + _duration(
                    state.remaining, state.job.requested_rate_tflop_per_s
                )
                work = seconds * state.job.requested_rate_tflop_per_s
                segments.append(ExecutionSegment(state.job, rack, now, next_time, work))
                state.completed = fsum((state.completed, work))
                if finishes:
                    state.completion = next_time
                    state.active = False
                active_racks[_key(rack)] = rack
            for key, rack in active_racks.items():
                on_seconds[key] = on_seconds.get(key, 0.0) + seconds
                used_heat[rack.site_identifier] += seconds * _heat_per_second(rack)
            now = next_time

        for site in scenario.sites:
            site_racks = tuple(
                (rack, on_seconds[_key(rack)])
                for rack in racks
                if rack.site_identifier == site.identifier and _key(rack) in on_seconds
            )
            flow = execution_interval_flows(site, index, opening[site.identifier], site_racks)
            opening[site.identifier] = flow.storage_closing_kwh

    segment_tuple = tuple(segments)
    integrated = simulate_execution(scenario, jobs, racks, segment_tuple)
    by_id = {progress.job.identifier: progress for progress in integrated.progress}
    horizon = reference[-1].interval.end.astimezone(UTC)
    outcomes = tuple(
        JobOutcome(
            by_id[state.job.identifier],
            state.completion,
            (
                state.completion > state.job.deadline.astimezone(UTC)
                if state.completion is not None
                else horizon >= state.job.deadline.astimezone(UTC)
            ),
        )
        for state in states
    )
    return ScheduleResult(segment_tuple, outcomes, integrated)
