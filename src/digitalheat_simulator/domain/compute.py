"""Compute quantities and immutable ideal-workload definitions.

Work is measured in TFLOP (10**12 operations), and capacity and requested
rates are measured in TFLOP/s. These types do not infer rates from thermal power.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from math import isclose, isfinite

from digitalheat_simulator.domain.thermal import Rack

WORK_ABS_TOL_TFLOP = 1e-9
WORK_REL_TOL = 1e-12


def _finite(name: str, value: float, *, positive: bool = False) -> None:
    if type(value) not in (int, float) or not isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if value < 0 or (positive and value == 0):
        raise ValueError(f"{name} must be {'positive' if positive else 'nonnegative'}")


@dataclass(frozen=True)
class ComputeRack:
    identifier: str
    site_identifier: str
    thermal: Rack
    capacity_tflop_per_s: float
    available_capacity_tflop_per_s: float

    def __post_init__(self) -> None:
        for name in ("identifier", "site_identifier"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be nonempty")
        if not isinstance(self.thermal, Rack):
            raise TypeError("thermal must be a Rack")
        _finite("capacity", self.capacity_tflop_per_s)
        _finite("available capacity", self.available_capacity_tflop_per_s)
        if self.available_capacity_tflop_per_s > self.capacity_tflop_per_s:
            raise ValueError("available capacity must not exceed installed capacity")


@dataclass(frozen=True)
class Job:
    identifier: str
    workload_type: str
    release: datetime
    deadline: datetime
    required_work_tflop: float
    requested_rate_tflop_per_s: float
    eligible_sites: tuple[str, ...]
    interruptible: bool
    pause_step_tflop: float | None = None

    def __post_init__(self) -> None:
        for name in ("identifier", "workload_type"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be nonempty")
        if self.release.utcoffset() is None or self.deadline.utcoffset() is None:
            raise ValueError("release and deadline must be timezone-aware")
        if self.deadline.astimezone(UTC) < self.release.astimezone(UTC):
            raise ValueError("deadline must not precede release")
        _finite("required work", self.required_work_tflop, positive=True)
        _finite("requested rate", self.requested_rate_tflop_per_s, positive=True)
        if (
            not isinstance(self.eligible_sites, tuple)
            or not self.eligible_sites
            or any(not isinstance(site, str) or not site.strip() for site in self.eligible_sites)
            or len(set(self.eligible_sites)) != len(self.eligible_sites)
        ):
            raise ValueError("eligible sites must be a nonempty tuple of unique identifiers")
        if type(self.interruptible) is not bool:
            raise ValueError("interruptible must be a boolean")
        if self.pause_step_tflop is not None:
            _finite("pause step", self.pause_step_tflop)
            if not self.interruptible:
                raise ValueError("non-interruptible jobs cannot have a pause step")


@dataclass(frozen=True)
class JobProgress:
    job: Job
    completed_work_tflop: float
    remaining_work_tflop: float

    def __post_init__(self) -> None:
        if not isinstance(self.job, Job):
            raise TypeError("job must be a Job")
        _finite("completed work", self.completed_work_tflop)
        _finite("remaining work", self.remaining_work_tflop)
        if not isclose(
            self.completed_work_tflop + self.remaining_work_tflop,
            self.job.required_work_tflop,
            rel_tol=WORK_REL_TOL,
            abs_tol=WORK_ABS_TOL_TFLOP,
        ):
            raise ValueError("completed and remaining work do not conserve required work")
        if self.completed_work_tflop > self.job.required_work_tflop:
            raise ValueError("completed work exceeds required work")
