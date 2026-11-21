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
from digitalheat_simulator.simulation.compute_thermal import (
    RackOnInterval,
    simulate_execution,
    simulate_rack_intervals,
)
from digitalheat_simulator.workload.execution import ExecutionSegment

START = datetime(2025, 1, 1, tzinfo=UTC)
END = START + timedelta(hours=1)
THERMAL = Rack(1, 1, 0.8)
RACK = ComputeRack("rack", "house", THERMAL, 2, 2)


def site(identifier, demand, rack_count=1):
    interval = Interval(START, END)
    series = ThermalDemandSeries(
        identifier, (DemandPoint(interval, demand),), Provenance("test", unit="kWh")
    )
    group = RackGroup("racks", THERMAL, rack_count, (OperationPoint(interval, False),))
    return SiteGroup(identifier, "synthetic", 1, series, (group,), 0, 0)


def job(identifier="job", work=1800, rate=2, sites=("house",)):
    return Job(identifier, "synthetic", START, END, work, rate, sites, True)


def segment(item, start, end, rack=RACK):
    return ExecutionSegment(
        item,
        rack,
        START + timedelta(seconds=start),
        START + timedelta(seconds=end),
        (end - start) * item.requested_rate_tflop_per_s,
    )


def test_1800_tflop_fractional_hour_reference():
    item = job()
    result = simulate_execution(
        Scenario((site("house", 1),)), (item,), (RACK,), (segment(item, 0, 900),)
    )
    flow = result.thermal.intervals[0].flows
    assert result.progress[0].remaining_work_tflop == 0
    assert flow.electrical_energy_kwh == pytest.approx(0.25)
    assert flow.gross_heat_kwh == pytest.approx(0.25)
    assert flow.recoverable_heat_kwh == pytest.approx(0.20)
    assert flow.direct_supply_kwh == pytest.approx(0.20)
    assert flow.backup_heat_kwh == pytest.approx(0.80)
    usage = result.racks[0]
    assert usage.on_seconds == 900
    assert usage.delivered_work_tflop == 1800
    assert usage.period_utilization == pytest.approx(0.25)
    assert usage.on_utilization == pytest.approx(1)
    flow.validate_balances()


def test_shared_rack_counts_union_and_sites_are_isolated():
    first, second = job("a", 900, 1), job("b", 900, 1)
    scenario = Scenario((site("house", 0), site("pool", 2, rack_count=0)))
    result = simulate_execution(
        scenario, (first, second), (RACK,), (segment(first, 0, 900), segment(second, 450, 1350))
    )
    house, pool = (row.per_site_flows[0] for row in result.thermal.sites)
    assert house.electrical_energy_kwh == pytest.approx(1350 / 3600)
    assert house.dumped_heat_kwh == pytest.approx(0.8 * 1350 / 3600)
    assert pool.backup_heat_kwh == 2
    assert pool.direct_supply_kwh == 0
    assert result.thermal.intervals[0].flows.backup_heat_kwh == 2


def test_rejects_mismatched_inventory():
    with pytest.raises(ValueError, match="inventory"):
        simulate_execution(Scenario((site("house", 1),)), (), (), ())


def test_execution_spanning_intervals_is_split_before_local_balance():
    intervals = (Interval(START, END), Interval(END, END + timedelta(hours=1)))
    demand = ThermalDemandSeries(
        "house", tuple(DemandPoint(item, 1) for item in intervals), Provenance("test", unit="kWh")
    )
    group = RackGroup("racks", THERMAL, 1, tuple(OperationPoint(item, False) for item in intervals))
    scenario = Scenario((SiteGroup("house", "house", 1, demand, (group,), 0, 0),))
    item = job(work=7200)
    result = simulate_execution(scenario, (item,), (RACK,), (segment(item, 1800, 5400),))
    assert [row.flows.electrical_energy_kwh for row in result.thermal.intervals] == [0.5, 0.5]
    assert [row.flows.recoverable_heat_kwh for row in result.thermal.intervals] == pytest.approx(
        [0.4, 0.4]
    )
    assert result.racks[0].on_seconds == 3600


def test_observed_rack_intervals_union_and_site_isolation():
    scenario = Scenario((site("house", 0), site("pool", 2, rack_count=0)))
    intervals = (
        RackOnInterval(RACK, START, START + timedelta(seconds=900)),
        RackOnInterval(RACK, START + timedelta(seconds=450), START + timedelta(seconds=1350)),
    )
    result = simulate_rack_intervals(scenario, (RACK,), intervals)
    house, pool = (row.per_site_flows[0] for row in result.sites)
    assert house.electrical_energy_kwh == pytest.approx(1350 / 3600)
    assert house.dumped_heat_kwh == pytest.approx(0.8 * 1350 / 3600)
    assert pool.backup_heat_kwh == 2
    assert pool.direct_supply_kwh == 0


def test_observed_rack_intervals_reject_unregistered_rack_and_outside_horizon():
    scenario = Scenario((site("house", 1),))
    other = ComputeRack("other", "house", THERMAL, 2, 2)
    with pytest.raises(ValueError, match="unknown"):
        simulate_rack_intervals(scenario, (RACK,), (RackOnInterval(other, START, END),))
    with pytest.raises(ValueError, match="outside"):
        simulate_rack_intervals(
            scenario, (RACK,), (RackOnInterval(RACK, START, END + timedelta(seconds=1)),)
        )


def test_observed_rack_interval_crossing_thermal_boundaries():
    intervals = (Interval(START, END), Interval(END, END + timedelta(hours=1)))
    demand = ThermalDemandSeries(
        "house", tuple(DemandPoint(item, 1) for item in intervals), Provenance("test", unit="kWh")
    )
    group = RackGroup("racks", THERMAL, 1, tuple(OperationPoint(item, False) for item in intervals))
    scenario = Scenario((SiteGroup("house", "house", 1, demand, (group,), 0, 0),))
    result = simulate_rack_intervals(
        scenario,
        (RACK,),
        (RackOnInterval(RACK, START + timedelta(minutes=30), END + timedelta(minutes=30)),),
    )
    assert [row.flows.electrical_energy_kwh for row in result.intervals] == [0.5, 0.5]
    assert [row.flows.recoverable_heat_kwh for row in result.intervals] == pytest.approx([0.4, 0.4])
