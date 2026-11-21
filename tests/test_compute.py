from datetime import UTC, datetime, timedelta

import pytest
from pint.errors import DimensionalityError

from digitalheat_simulator.domain.compute import ComputeRack, Job, JobProgress
from digitalheat_simulator.domain.thermal import Rack
from digitalheat_simulator.domain.units import convert


def job(**overrides):
    start = datetime(2025, 1, 1, tzinfo=UTC)
    values = {
        "identifier": "job",
        "workload_type": "synthetic",
        "release": start,
        "deadline": start + timedelta(seconds=30),
        "required_work_tflop": 60,
        "requested_rate_tflop_per_s": 2,
        "eligible_sites": ("site",),
        "interruptible": True,
    }
    values.update(overrides)
    return Job(**values)


def test_work_and_rate_units_are_distinct():
    assert convert(1, "TFLOP", "FLOP") == pytest.approx(1e12)
    assert convert(1, "TFLOPS", "GFLOPS") == pytest.approx(1000)
    with pytest.raises(DimensionalityError):
        convert(1, "TFLOP", "TFLOPS")


def test_job_progress_conserves_work():
    item = job()
    progress = JobProgress(item, 20, 40)
    assert progress.completed_work_tflop + progress.remaining_work_tflop == 60
    with pytest.raises(ValueError, match="conserve"):
        JobProgress(item, 20, 41)
    with pytest.raises(ValueError):
        JobProgress(item, 61, 0)


@pytest.mark.parametrize(
    "changes",
    [
        {"required_work_tflop": 0},
        {"requested_rate_tflop_per_s": float("nan")},
        {"eligible_sites": ()},
        {"eligible_sites": ("a", "a")},
        {"interruptible": False, "pause_step_tflop": 1},
        {"pause_step_tflop": -1},
        {"release": datetime(2025, 1, 1)},
    ],
)
def test_invalid_jobs_rejected(changes):
    with pytest.raises(ValueError):
        job(**changes)


def test_rack_capacity_is_separate_from_power():
    thermal = Rack(1, 1, 0.8)
    rack = ComputeRack("rack", "site", thermal, 10, 5)
    assert rack.available_capacity_tflop_per_s == 5
    assert rack.thermal.electrical_power_kw == 1
    with pytest.raises(ValueError):
        ComputeRack("rack", "site", thermal, 1, 2)
