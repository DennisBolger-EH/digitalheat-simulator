from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from digitalheat_simulator.domain.compute import ComputeRack, Job
from digitalheat_simulator.domain.parameters import Provenance
from digitalheat_simulator.domain.scenario import (
    DemandPoint,
    Interval,
    OperationPoint,
    RackGroup,
    Scenario,
    SiteGroup,
    ThermalDemandSeries,
)
from digitalheat_simulator.domain.thermal import Rack
from digitalheat_simulator.workload.scheduler import schedule

START = datetime(2025, 1, 1, tzinfo=UTC)
THERMAL = Rack(1, 1, 0.8)
SOURCE = Provenance("synthetic", unit="kWh")


def make_site(name, demands, count=1, capacity=0, initial=0, kind="house"):
    points = tuple(
        DemandPoint(Interval(START + timedelta(hours=i), START + timedelta(hours=i + 1)), demand)
        for i, demand in enumerate(demands)
    )
    group = RackGroup(
        "group", THERMAL, count, tuple(OperationPoint(p.interval, False) for p in points)
    )
    return SiteGroup(
        name, kind, 1, ThermalDemandSeries(name, points, SOURCE), (group,), capacity, initial
    )


def rack(site="house", name="r", capacity=2):
    return ComputeRack(name, site, THERMAL, capacity, capacity)


def job(
    name="job",
    work=1800,
    rate=2,
    release=0,
    deadline=3600,
    sites=("house",),
    interruptible=True,
    step=None,
):
    return Job(
        name,
        "synthetic",
        START + timedelta(seconds=release),
        START + timedelta(seconds=deadline),
        work,
        rate,
        sites,
        interruptible,
        step,
    )


def test_no_jobs():
    result = schedule(Scenario((make_site("house", [1]),)), (), (rack(),))
    assert result.segments == ()
    assert result.integrated.thermal.intervals[0].flows.backup_heat_kwh == 1


def test_reference_fractional_hour_and_work_conservation():
    result = schedule(Scenario((make_site("house", [1]),)), (job(),), (rack(),))
    assert result.outcomes[0].completion == START + timedelta(seconds=900)
    progress = result.outcomes[0].progress
    assert progress.completed_work_tflop == 1800
    assert progress.remaining_work_tflop == 0
    assert not result.outcomes[0].deadline_missed
    flow = result.integrated.thermal.intervals[0].flows
    assert flow.electrical_energy_kwh == pytest.approx(0.25)
    assert flow.gross_heat_kwh == pytest.approx(0.25)
    assert flow.recoverable_heat_kwh == pytest.approx(0.2)
    flow.validate_balances()


@pytest.mark.parametrize(
    ("release", "work", "deadline", "completion", "missed"),
    [(0, 3600, 3600, 1800, False), (900, 3600, 2700, 2700, False), (900, 7200, 2700, None, True)],
)
def test_release_and_deadline_outcomes(release, work, deadline, completion, missed):
    item = job(work=work, release=release, deadline=deadline)
    result = schedule(Scenario((make_site("house", [2]),)), (item,), (rack(),))
    assert result.outcomes[0].completion == (
        START + timedelta(seconds=completion) if completion is not None else None
    )
    assert result.outcomes[0].deadline_missed is missed
    assert all(segment.start >= item.release for segment in result.segments)


def test_job_finishes_late_and_continues():
    item = job(work=7200, deadline=1800)
    result = schedule(Scenario((make_site("house", [2, 2]),)), (item,), (rack(),))
    assert result.outcomes[0].completion == START + timedelta(hours=1)
    assert result.outcomes[0].deadline_missed


def test_concurrent_jobs_share_rack_without_double_heat():
    jobs = (
        job("a", work=900, rate=1, deadline=7200),
        job("b", work=900, rate=1, deadline=7200),
    )
    result = schedule(Scenario((make_site("house", [0.2]),)), jobs, (rack(),))
    assert all(outcome.completion == START + timedelta(seconds=900) for outcome in result.outcomes)
    assert result.integrated.thermal.intervals[0].flows.electrical_energy_kwh == pytest.approx(0.25)
    assert result.integrated.thermal.intervals[0].flows.dumped_heat_kwh == pytest.approx(0)
    assert sum(segment.delivered_work_tflop for segment in result.segments) == 1800


def test_capacity_limit_and_earliest_deadline():
    jobs = (job("a", work=1800, rate=2, deadline=3600), job("b", work=1800, rate=2, deadline=1800))
    result = schedule(Scenario((make_site("house", [2]),)), jobs, (rack(),))
    assert result.outcomes[1].completion == START + timedelta(seconds=900)
    assert result.outcomes[0].completion == START + timedelta(seconds=1800)


def test_competing_jobs_start_early_enough_even_without_useful_heat():
    jobs = (job("a", work=1800, deadline=3600), job("b", work=1800, deadline=3600))
    result = schedule(Scenario((make_site("house", [0]),)), jobs, (rack(),))
    assert result.segments[0].start == START + timedelta(seconds=1800)
    assert result.outcomes[0].completion == START + timedelta(seconds=2700)
    assert result.outcomes[1].completion == START + timedelta(seconds=3600)
    assert all(not outcome.deadline_missed for outcome in result.outcomes)
    assert result.integrated.thermal.intervals[0].flows.dumped_heat_kwh == pytest.approx(0.4)


def test_shared_capacity_contention_protects_deadlines():
    jobs = tuple(job(name, work=1800, rate=1, deadline=3600) for name in ("a", "b", "c"))
    result = schedule(Scenario((make_site("house", [0]),)), jobs, (rack(),))
    assert result.segments[0].start == START
    assert all(not outcome.deadline_missed for outcome in result.outcomes)
    assert result.integrated.thermal.intervals[0].flows.electrical_energy_kwh == pytest.approx(1)


def test_multirack_contention_does_not_defer_all_jobs_to_last_start():
    scenario = Scenario((make_site("house", [0], count=2),))
    jobs = tuple(job(name, work=1800, deadline=1800) for name in ("a", "b", "c"))
    result = schedule(scenario, jobs, (rack(name="a"), rack(name="b")))
    assert all(not outcome.deadline_missed for outcome in result.outcomes)
    assert result.segments[0].start == START


def test_future_arrival_is_accounted_for_before_deferring_current_work():
    first = job("a", work=1800, deadline=3600)
    later = job("b", work=1800, release=2700, deadline=3600)
    result = schedule(Scenario((make_site("house", [0]),)), (first, later), (rack(),))
    assert result.outcomes[0].completion == START + timedelta(seconds=2700)
    assert result.outcomes[1].completion == START + timedelta(seconds=3600)
    assert all(not outcome.deadline_missed for outcome in result.outcomes)


@pytest.mark.parametrize(
    ("house", "pool", "chosen"), [(0.2, 1, "pool"), (1, 0.2, "house"), (1, 1, "house")]
)
def test_thermal_preference_is_consumer_agnostic_and_deterministic(house, pool, chosen):
    scenario = Scenario((make_site("house", [house]), make_site("pool", [pool], kind="pool")))
    item = job(sites=("house", "pool"))
    result = schedule(scenario, (item,), (rack("house"), rack("pool")))
    assert result.segments[0].rack.site_identifier == chosen
    assert result == schedule(scenario, (item,), (rack("pool"), rack("house")))


def test_reservations_cannot_double_count_demand():
    scenario = Scenario((make_site("house", [0.2], count=2),))
    jobs = (job("a", work=1800, rate=2, deadline=7200), job("b", work=1800, rate=2, deadline=7200))
    result = schedule(scenario, jobs, (rack(name="a"), rack(name="b")))
    assert result.outcomes[0].progress.completed_work_tflop == pytest.approx(1800)
    assert result.outcomes[1].progress.completed_work_tflop == 0
    assert result.integrated.thermal.intervals[0].flows.recoverable_heat_kwh == pytest.approx(0.2)


def test_full_storage_and_no_demand_prevents_nonurgent_execution():
    scenario = Scenario((make_site("house", [0], capacity=1, initial=1),))
    result = schedule(scenario, (job(deadline=7200),), (rack(),))
    assert result.segments == ()
    assert result.outcomes[0].progress.remaining_work_tflop == 1800


def test_critical_job_runs_despite_dumping():
    scenario = Scenario((make_site("house", [0]),))
    result = schedule(scenario, (job(deadline=900),), (rack(),))
    assert result.outcomes[0].completion == START + timedelta(seconds=900)
    assert result.integrated.thermal.intervals[0].flows.dumped_heat_kwh == pytest.approx(0.2)


def test_deadline_feasibility_precedes_thermal_preference():
    scenario = Scenario((make_site("house", [0.2]), make_site("pool", [2], kind="pool")))
    later = job("later", work=3600, deadline=6000, sites=("house", "pool"), interruptible=False)
    earlier = job("earlier", work=1800, release=100, deadline=1000, sites=("pool",))
    result = schedule(scenario, (later, earlier), (rack("house"), rack("pool")))
    assert (
        next(segment for segment in result.segments if segment.job == later).rack.site_identifier
        == "house"
    )
    assert result.outcomes[1].completion == START + timedelta(seconds=1000)
    assert not result.outcomes[1].deadline_missed


def test_placement_also_protects_later_deadline_when_an_alternative_exists():
    scenario = Scenario((make_site("house", [0.2]), make_site("pool", [2], kind="pool")))
    first = job("first", work=3600, deadline=1900, sites=("house", "pool"), interruptible=False)
    second = job("second", work=2000, release=100, deadline=2000, sites=("pool",))
    result = schedule(scenario, (first, second), (rack("house"), rack("pool")))
    assert result.segments[0].rack.site_identifier == "house"
    assert all(not outcome.deadline_missed for outcome in result.outcomes)


def test_current_competing_job_uses_feasible_site_over_hotter_site():
    scenario = Scenario((make_site("house", [0]), make_site("pool", [2], kind="pool")))
    first = job("a", work=1800, deadline=900, sites=("house", "pool"))
    second = job("b", work=1800, deadline=900, sites=("pool",))
    result = schedule(scenario, (first, second), (rack("house"), rack("pool")))
    first_segment = next(segment for segment in result.segments if segment.job == first)
    assert first_segment.rack.site_identifier == "house"
    assert all(not outcome.deadline_missed for outcome in result.outcomes)


@pytest.mark.parametrize("step", [None, 0])
def test_arbitrary_pause_and_resume(step):
    scenario = Scenario((make_site("house", [0.1, 0.1]),))
    item = job(work=1800, deadline=9000, step=step)
    result = schedule(scenario, (item,), (rack(),))
    assert result.segments[0].end == START + timedelta(seconds=450)
    assert result.segments[1].start == START + timedelta(hours=1)
    assert result.outcomes[0].completion == START + timedelta(hours=1, seconds=450)


def test_checkpoint_pause_and_final_partial_step():
    scenario = Scenario((make_site("house", [0.1, 0.2]),))
    item = job(work=1350, deadline=10000, step=900)
    result = schedule(scenario, (item,), (rack(),))
    assert result.segments[0].delivered_work_tflop == 900
    assert result.segments[1].start == START + timedelta(hours=1)
    assert result.outcomes[0].progress.remaining_work_tflop == 0


def test_checkpoint_job_waits_when_next_step_exceeds_budget():
    scenario = Scenario((make_site("house", [0.05, 0.1]),))
    item = job(work=900, deadline=10000, step=900)
    result = schedule(scenario, (item,), (rack(),))
    assert result.segments[0].start == START + timedelta(hours=1)
    assert result.outcomes[0].progress.remaining_work_tflop == 0


def test_bodycam_step_units_with_nonmultiple_completion():
    scenario = Scenario((make_site("house", [0.8 * 42 / 3600, 0.1]),))
    item = job(work=0.5, rate=0.01, deadline=10000, step=0.42)
    result = schedule(scenario, (item,), (rack(),))
    assert result.segments[0].delivered_work_tflop == pytest.approx(0.42)
    assert result.segments[1].start == START + timedelta(hours=1)
    assert result.outcomes[0].completion == START + timedelta(hours=1, seconds=8)


def test_insufficient_capacity_leaves_work_unfinished():
    item = job(rate=3)
    result = schedule(Scenario((make_site("house", [1]),)), (item,), (rack(),))
    assert result.segments == ()
    assert result.outcomes[0].progress.remaining_work_tflop == item.required_work_tflop
    assert result.outcomes[0].deadline_missed


def test_tiny_work_is_not_completed_at_an_intermediate_event():
    first = job("first", work=1e-10, rate=1e-12, deadline=1000)
    second = job("second", work=1e-10, rate=1e-12, release=1, deadline=1000)
    result = schedule(Scenario((make_site("house", [1]),)), (first, second), (rack(),))
    assert result.outcomes[0].completion == START + timedelta(seconds=100)
    assert result.outcomes[1].completion == START + timedelta(seconds=101)


def test_noninterruptible_continues_when_heat_opportunity_ends():
    scenario = Scenario((make_site("house", [0.1, 0]),))
    item = job(work=9000, deadline=10000, interruptible=False)
    result = schedule(scenario, (item,), (rack(),))
    assert result.outcomes[0].completion == START + timedelta(seconds=4500)
    assert result.integrated.thermal.intervals[1].flows.dumped_heat_kwh == pytest.approx(0.2)


def test_earlier_deadline_preempts_at_valid_checkpoint():
    scenario = Scenario((make_site("house", [2]),))
    later = job("later", work=3600, deadline=7200, step=600)
    earlier = job("earlier", work=600, release=200, deadline=1000)
    result = schedule(scenario, (later, earlier), (rack(),))
    first_earlier = next(segment for segment in result.segments if segment.job == earlier)
    assert first_earlier.start == START + timedelta(seconds=300)
    assert not result.outcomes[1].deadline_missed


@pytest.mark.parametrize("rate", [0.7, 3.3])
def test_fractional_rate_roundoff_does_not_reject_completed_work(rate):
    scenario = Scenario((make_site("house", [0.1, 0.1, 0.1]),))
    item = job(work=rate * 901, rate=rate, deadline=10000)
    result = schedule(scenario, (item,), (rack(capacity=4),))
    assert result.outcomes[0].progress.remaining_work_tflop == pytest.approx(0, abs=1e-9)
    assert result.outcomes[0].completion is not None


def test_rejects_nonoff_explicit_operation():
    site = make_site("house", [1])
    group = replace(
        site.racks[0], operation=(OperationPoint(site.demand.points[0].interval, True),)
    )
    with pytest.raises(ValueError, match="operations"):
        schedule(Scenario((replace(site, racks=(group,)),)), (), (rack(),))
