from datetime import UTC, datetime, timedelta

import pytest

from digitalheat_simulator.domain.compute import ComputeRack, Job
from digitalheat_simulator.domain.thermal import Rack
from digitalheat_simulator.workload.execution import (
    ExecutionSegment,
    rack_on_seconds,
    validate_execution,
)

START = datetime(2025, 1, 1, tzinfo=UTC)
RACK = ComputeRack("r", "site", Rack(1, 1, 0.8), 4, 4)


def item(name, rate):
    return Job(name, "synthetic", START, START + timedelta(seconds=30), 60, rate, ("site",), True)


def segment(job, start, end):
    return ExecutionSegment(
        job,
        RACK,
        START + timedelta(seconds=start),
        START + timedelta(seconds=end),
        (end - start) * job.requested_rate_tflop_per_s,
    )


def test_concurrent_jobs_respect_capacity_and_conserve_work():
    a, b = item("a", 2), item("b", 2)
    progress = validate_execution((a, b), (RACK,), (segment(a, 0, 10), segment(b, 0, 10)))
    assert [p.completed_work_tflop for p in progress] == [20, 20]
    assert [p.remaining_work_tflop for p in progress] == [40, 40]


def test_overcommitted_capacity_and_job_overlap_fail():
    a, b = item("a", 3), item("b", 2)
    with pytest.raises(ValueError, match="capacity exceeded"):
        validate_execution((a, b), (RACK,), (segment(a, 0, 10), segment(b, 0, 10)))
    with pytest.raises(ValueError, match="concurrently"):
        validate_execution((b,), (RACK,), (segment(b, 0, 10), segment(b, 5, 15)))


def test_release_and_delivered_rate_are_validated():
    a = item("a", 2)
    with pytest.raises(ValueError, match="release"):
        segment(a, -1, 1)
    with pytest.raises(ValueError, match="rate times"):
        ExecutionSegment(a, RACK, START, START + timedelta(seconds=5), 9)


def test_rack_on_time_is_union_and_clipped_to_interval():
    a, b = item("a", 2), item("b", 2)
    segments = (segment(a, 0, 10), segment(b, 5, 15))
    validate_execution((a, b), (RACK,), segments)
    assert rack_on_seconds(segments, RACK, START, START + timedelta(seconds=30)) == 15
    assert (
        rack_on_seconds(segments, RACK, START + timedelta(seconds=7), START + timedelta(seconds=12))
        == 5
    )


def test_checkpoint_pause_only_on_work_step_and_completion_need_not_be_step():
    from dataclasses import replace

    a = replace(item("a", 2), required_work_tflop=25, pause_step_tflop=10)
    validate_execution((a,), (RACK,), (segment(a, 0, 5), segment(a, 10, 17.5)))
    with pytest.raises(ValueError, match="pause step"):
        validate_execution((a,), (RACK,), (segment(a, 0, 4), segment(a, 10, 18.5)))


@pytest.mark.parametrize("step", [None, 0])
def test_arbitrary_pause_step(step):
    from dataclasses import replace

    a = replace(item("a", 2), pause_step_tflop=step)
    validate_execution((a,), (RACK,), (segment(a, 0, 3), segment(a, 5, 10)))


def test_horizon_checks_final_interruption_without_treating_horizon_as_pause():
    from dataclasses import replace

    checkpointed = replace(item("a", 2), pause_step_tflop=10)
    with pytest.raises(ValueError, match="pause step"):
        validate_execution(
            (checkpointed,),
            (RACK,),
            (segment(checkpointed, 0, 4),),
            horizon=START + timedelta(seconds=20),
        )
    validate_execution(
        (checkpointed,),
        (RACK,),
        (segment(checkpointed, 0, 4),),
        horizon=START + timedelta(seconds=4),
    )
    noninterruptible = replace(item("b", 2), interruptible=False)
    with pytest.raises(ValueError, match="cannot stop"):
        validate_execution(
            (noninterruptible,),
            (RACK,),
            (segment(noninterruptible, 0, 4),),
            horizon=START + timedelta(seconds=20),
        )
