import math
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from digitalheat_simulator.data.pool_demand import pool_demand
from digitalheat_simulator.data.reference_house import reconstruct_2025
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
from digitalheat_simulator.simulation.scenario import EnergyFlows, simulate_scenario
from digitalheat_simulator.simulation.thermal import simulate

START = datetime(2025, 1, 1, tzinfo=UTC)
PROVENANCE = Provenance("test input", unit="kWh", applicability="synthetic test")
RACK = Rack(1, 1, 0.8)
WEATHER = Path("case_materials") / "open-meteo-47.56N7.55E283m.csv"


def series(name, values):
    return ThermalDemandSeries(
        name,
        tuple(
            DemandPoint(Interval(START + timedelta(hours=i), START + timedelta(hours=i + 1)), v)
            for i, v in enumerate(values)
        ),
        PROVENANCE,
    )


def rack_group(demand, count=1, rack=RACK, on=True, name="rack"):
    return RackGroup(
        name, rack, count, tuple(OperationPoint(p.interval, on) for p in demand.points)
    )


def site(name, demand, count=1, racks=(), capacity=0, initial=0, kind="house"):
    return SiteGroup(name, kind, count, demand, racks, capacity, initial)


def test_isolated_sites_and_distinct_racks():
    house = series("house", [0])
    pool = pool_demand("pool", series("temp", [2]).points, PROVENANCE)
    result = simulate_scenario(
        Scenario(
            (
                site("home", house, racks=(rack_group(house, count=2),)),
                site("pool", pool, racks=(rack_group(pool, rack=Rack(2, 1, 0.5)),), kind="pool"),
            )
        )
    )
    home, swimming = (r.per_site_flows[0] for r in result.sites)
    assert home.dumped_heat_kwh == pytest.approx(1.6)
    assert swimming.backup_heat_kwh == pytest.approx(1.5)
    assert swimming.direct_supply_kwh == pytest.approx(0.5)
    assert result.rack_count == 3
    assert result.site_counts == {"house": 1, "pool": 1}
    assert result.intervals[0].flows.backup_heat_kwh == pytest.approx(1.5)
    assert result.intervals[0].flows.dumped_heat_kwh == pytest.approx(1.6)
    aggregate = result.intervals[0].flows
    for field in fields(EnergyFlows):
        assert getattr(aggregate, field.name) == pytest.approx(
            sum(
                getattr(group.per_site_flows[0], field.name) * group.site.quantity
                for group in result.sites
            )
        )
    assert aggregate.demand_kwh == pytest.approx(
        aggregate.direct_supply_kwh + aggregate.storage_discharge_kwh + aggregate.backup_heat_kwh
    )
    assert aggregate.recoverable_heat_kwh == pytest.approx(
        aggregate.direct_supply_kwh + aggregate.storage_charge_kwh + aggregate.dumped_heat_kwh
    )
    assert aggregate.storage_closing_kwh == pytest.approx(
        aggregate.storage_opening_kwh
        + aggregate.storage_charge_kwh
        - aggregate.storage_discharge_kwh
    )
    aggregate.validate_balances()


def test_reassigning_racks_changes_local_results():
    house, pool = series("house", [0]), series("pool", [2])
    without = simulate_scenario(Scenario((site("house", house), site("pool", pool, kind="pool"))))
    assigned = simulate_scenario(
        Scenario((site("house", house), site("pool", pool, racks=(rack_group(pool),), kind="pool")))
    )
    assert without.intervals[0].flows.backup_heat_kwh == 2
    assert assigned.intervals[0].flows.backup_heat_kwh == pytest.approx(1.2)


@pytest.mark.parametrize("initial", [0, 0.5, 1])
def test_identical_group_equals_independent_copies(initial):
    demand = series("house", [0, 1, 2, 0])
    racks = (rack_group(demand),)
    grouped = simulate_scenario(Scenario((site("group", demand, 3, racks, 1, initial),)))
    copies = simulate_scenario(
        Scenario(tuple(site(f"copy-{i}", demand, 1, racks, 1, initial) for i in range(3)))
    )
    assert grouped == simulate_scenario(grouped.scenario)
    for left, right in zip(grouped.intervals, copies.intervals, strict=True):
        for field in fields(EnergyFlows):
            assert getattr(left.flows, field.name) == pytest.approx(
                getattr(right.flows, field.name), abs=1e-9, rel=1e-12
            )


def test_multiple_rack_groups_and_zero_racks():
    demand = series("d", [3])
    racks = (
        rack_group(demand, 2, RACK, name="a"),
        rack_group(demand, 1, Rack(3, 2, 0.5), name="b"),
        rack_group(demand, 7, RACK, on=False, name="c"),
    )
    result = simulate_scenario(Scenario((site("home", demand, racks=racks),)))
    f = result.intervals[0].flows
    assert f.electrical_energy_kwh == 5
    assert f.gross_heat_kwh == 4
    assert f.recoverable_heat_kwh == pytest.approx(2.6)
    assert f.backup_heat_kwh == pytest.approx(0.4)
    assert result.rack_count == 10
    zero = simulate_scenario(Scenario((site("no-racks", demand),)))
    assert zero.intervals[0].flows.backup_heat_kwh == 3


def test_reject_mismatch_counts_and_operation():
    demand = series("d", [1])
    other = series("other", [1, 1])
    with pytest.raises(ValueError, match="intervals must match"):
        Scenario((site("a", demand), site("b", other)))
    with pytest.raises(ValueError, match="lengths"):
        site("a", demand, racks=(rack_group(other),))
    with pytest.raises(ValueError, match="quantity"):
        site("a", demand, count=0)
    with pytest.raises(ValueError, match="quantity"):
        rack_group(demand, count=True)
    with pytest.raises(ValueError, match="storage"):
        site("a", demand, capacity=1, initial=2)
    with pytest.raises(ValueError, match="unique"):
        Scenario((site("a", demand), site("a", demand)))


def test_dst_fold_match_by_instant_not_wall_clock():
    zone = ZoneInfo("Europe/Zurich")
    first = datetime(2025, 10, 26, 2, tzinfo=zone, fold=0)
    second = datetime(2025, 10, 26, 2, tzinfo=zone, fold=1)
    three = datetime(2025, 10, 26, 3, tzinfo=zone)
    demand = ThermalDemandSeries("dst", (DemandPoint(Interval(first, second), 1),), PROVENANCE)
    wrong = RackGroup("r", RACK, 1, (OperationPoint(Interval(second, three), True),))
    with pytest.raises(ValueError, match="interval must match"):
        site("dst", demand, racks=(wrong,))


def test_reference_m1_regression():
    if not WEATHER.exists():
        pytest.skip("user-supplied weather CSV is not present")
    reference = reconstruct_2025(WEATHER, (True,) * 8760)
    demand = reference.as_demand_series()
    m1 = simulate(reference.intervals, RACK, 35, 0)
    m2 = simulate_scenario(
        Scenario((site("reference", demand, racks=(rack_group(demand),), capacity=35),))
    )
    names = [f.name for f in fields(EnergyFlows)]
    for original, result in zip(m1.results, m2.intervals, strict=True):
        for name in names:
            assert getattr(result.flows, name) == pytest.approx(
                getattr(original, name), abs=1e-9, rel=1e-12
            )
    expected = {
        "demand_kwh": 31231.015625,
        "electrical_energy_kwh": 8760,
        "gross_heat_kwh": 8760,
        "recoverable_heat_kwh": 7008,
        "direct_supply_kwh": 5861.6984375,
        "storage_charge_kwh": 243.3015625,
        "storage_discharge_kwh": 243.3015625,
        "dumped_heat_kwh": 903,
        "backup_heat_kwh": 25126.015625,
    }
    for name, value in expected.items():
        assert math.fsum(getattr(row.flows, name) for row in m2.intervals) == pytest.approx(
            value, abs=1e-9, rel=1e-12
        )
    assert m2.intervals[-1].flows.storage_closing_kwh == 0
