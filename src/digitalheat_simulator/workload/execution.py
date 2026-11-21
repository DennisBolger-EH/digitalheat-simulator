"""Validation of ideal execution segments, without scheduling or real processes."""

from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from math import fsum, isclose, isfinite

from digitalheat_simulator.domain.compute import (
    WORK_ABS_TOL_TFLOP,
    WORK_REL_TOL,
    ComputeRack,
    Job,
    JobProgress,
)


@dataclass(frozen=True)
class ExecutionSegment:
    job: Job
    rack: ComputeRack
    start: datetime
    end: datetime
    delivered_work_tflop: float

    def __post_init__(self) -> None:
        if not isinstance(self.job, Job) or not isinstance(self.rack, ComputeRack):
            raise TypeError("segment requires a Job and ComputeRack")
        if self.start.utcoffset() is None or self.end.utcoffset() is None:
            raise ValueError("execution times must be timezone-aware")
        start = self.start.astimezone(UTC)
        end = self.end.astimezone(UTC)
        if start < self.job.release.astimezone(UTC) or end <= start:
            raise ValueError("execution must occur after release with positive duration")
        if self.rack.site_identifier not in self.job.eligible_sites:
            raise ValueError("rack site is not eligible")
        if self.job.requested_rate_tflop_per_s > self.rack.available_capacity_tflop_per_s:
            raise ValueError("requested rate exceeds available rack capacity")
        if type(self.delivered_work_tflop) not in (int, float):
            raise ValueError("delivered work must be a positive finite number")
        if not isfinite(self.delivered_work_tflop) or self.delivered_work_tflop <= 0:
            raise ValueError("delivered work must be a positive finite number")
        expected = self.job.requested_rate_tflop_per_s * (end - start).total_seconds()
        if not isclose(
            self.delivered_work_tflop,
            expected,
            rel_tol=WORK_REL_TOL,
            abs_tol=WORK_ABS_TOL_TFLOP,
        ):
            raise ValueError("delivered work must match rate times elapsed seconds")


def validate_execution(
    jobs: tuple[Job, ...], racks: tuple[ComputeRack, ...], segments: tuple[ExecutionSegment, ...]
) -> tuple[JobProgress, ...]:
    """Validate identities, placement, no overlap per job, capacity and work conservation."""
    jobs_by_id = {job.identifier: job for job in jobs}
    racks_by_id = {(rack.site_identifier, rack.identifier): rack for rack in racks}
    if len(jobs_by_id) != len(jobs) or len(racks_by_id) != len(racks):
        raise ValueError("job and site-local rack identifiers must be unique")
    by_job: dict[str, list[ExecutionSegment]] = {identifier: [] for identifier in jobs_by_id}
    events: dict[tuple[str, str], list[tuple[datetime, int, float]]] = {
        key: [] for key in racks_by_id
    }
    for segment in segments:
        job = segment.job
        key = (segment.rack.site_identifier, segment.rack.identifier)
        if jobs_by_id.get(job.identifier) != job or racks_by_id.get(key) != segment.rack:
            raise ValueError("segment references an unknown or mismatched job or rack")
        by_job[job.identifier].append(segment)
        rate = job.requested_rate_tflop_per_s
        events[key].append((segment.start.astimezone(UTC), 1, rate))
        events[key].append((segment.end.astimezone(UTC), 0, rate))
    for key, rack_events in events.items():
        rate = 0.0
        for _, kind, amount in sorted(rack_events):
            rate += amount if kind else -amount
            if rate > racks_by_id[key].available_capacity_tflop_per_s + 1e-12:
                raise ValueError(f"rack {key} capacity exceeded")
    progress = []
    for job in jobs:
        ordered = sorted(by_job[job.identifier], key=lambda item: item.start.astimezone(UTC))
        for previous, current in pairwise(ordered):
            if previous.end.astimezone(UTC) > current.start.astimezone(UTC):
                raise ValueError("a job cannot execute concurrently on multiple racks")
            if (previous.rack.site_identifier, previous.rack.identifier) != (
                current.rack.site_identifier,
                current.rack.identifier,
            ):
                raise ValueError("job migration is not supported")
            if not job.interruptible and previous.end.astimezone(UTC) != current.start.astimezone(
                UTC
            ):
                raise ValueError("a non-interruptible job cannot have an execution gap")
        completed = fsum(segment.delivered_work_tflop for segment in ordered)
        if completed > job.required_work_tflop:
            raise ValueError("execution exceeds job required work")
        progress.append(JobProgress(job, completed, job.required_work_tflop - completed))
    return tuple(progress)


def rack_on_seconds(
    segments: tuple[ExecutionSegment, ...],
    rack: ComputeRack,
    start: datetime,
    end: datetime,
) -> float:
    """Return union of execution times for one rack in a half-open interval."""
    if start.utcoffset() is None or end.utcoffset() is None:
        raise ValueError("interval bounds must be timezone-aware")
    start_utc, end_utc = start.astimezone(UTC), end.astimezone(UTC)
    if end_utc <= start_utc:
        raise ValueError("interval end must follow start")
    intervals = []
    for segment in segments:
        if segment.rack == rack:
            left = max(start_utc, segment.start.astimezone(UTC))
            right = min(end_utc, segment.end.astimezone(UTC))
            if left < right:
                intervals.append((left, right))
    intervals.sort()
    if not intervals:
        return 0.0
    left, right = intervals[0]
    duration = 0.0
    for next_left, next_right in intervals[1:]:
        if next_left <= right:
            right = max(right, next_right)
        else:
            duration += (right - left).total_seconds()
            left, right = next_left, next_right
    return duration + (right - left).total_seconds()
