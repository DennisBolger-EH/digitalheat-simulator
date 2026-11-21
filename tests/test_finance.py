from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from digitalheat_simulator.application.reference_economics import calculate
from digitalheat_simulator.domain.compute import ComputeRack, Job
from digitalheat_simulator.domain.parameters import Parameter, ParameterGroup, Provenance
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
from digitalheat_simulator.finance.model import (
    CostLine,
    Economics,
    RatePoint,
    SitePrices,
    economics_from_groups,
    evaluate,
)
from digitalheat_simulator.simulation.compute_thermal import RackOnInterval, simulate_rack_intervals
from digitalheat_simulator.simulation.scenario import simulate_scenario
from digitalheat_simulator.workload.scheduler import schedule

START = datetime(2025, 1, 1, tzinfo=UTC)
SOURCE = Provenance("synthetic test", unit="kWh")
RACK = Rack(1, 1, 0.8)
WEATHER = Path("case_materials") / "open-meteo-47.56N7.55E283m.csv"


def param(name, value, unit, scope="scenario"):
    return Parameter(
        name,
        value,
        "number",
        scope,
        unit,
        provenance=Provenance("synthetic test", unit=unit, applicability="synthetic test"),
    )


def scenario(hours=1, demand=1, on=True, quantity=1, racks=1, initial=0, storage=0, start=START):
    interval = Interval(start, start + timedelta(hours=hours))
    series = ThermalDemandSeries("d", (DemandPoint(interval, demand),), SOURCE)
    group = RackGroup("r", RACK, racks, (OperationPoint(interval, on),))
    site = SiteGroup("home", "house", quantity, series, (group,), storage, initial)
    return Scenario((site,))


def price(site="home", electricity=0.25, heat=0.1, backup=0.1):
    return SitePrices(
        site,
        param("electricity", electricity, "CHF/kWh"),
        param("heat", heat, "CHF/kWh"),
        param("backup", backup, "CHF/kWh"),
    )


def test_reference_tariff_and_year():
    if not WEATHER.exists():
        pytest.skip("user-supplied weather CSV is not present")
    result = calculate(WEATHER, 8760)
    prices = result.inputs.site_prices[0]
    assert prices.electricity.value == 0.3325
    assert prices.electricity.provenance.access_date is None
    assert prices.heat.value == pytest.approx(0.133)
    assert result.annual
    assert result.electricity_cost_chf.value == pytest.approx(2912.70)
    assert result.useful_heat_kwh.value == pytest.approx(6105.0)
    assert result.useful_heat_value_chf.value == pytest.approx(6105 * 0.133)
    assert result.case_break_even_chf_per_server_hour.value == pytest.approx(
        (2912.7 - 6105 * 0.133) / 8760
    )
    assert result.full_cost_break_even_chf_per_server_hour.value is None
    assert "hardware" in result.capex_chf.reason
    assert "compute sale price" in result.compute_income_chf.reason


def test_100_kwh_and_sold_hours_never_inferred():
    result = evaluate(simulate_scenario(scenario(hours=100)), Economics((price(),)))
    assert result.electricity_cost_chf.value == 25
    assert result.rack_hours.value == 100
    assert result.sold_server_hours.value is None
    assert result.case_break_even_chf_per_server_hour.value is None
    with pytest.raises(ValueError, match="exceed"):
        evaluate(
            simulate_scenario(scenario(hours=100)),
            Economics((price(),), sold_server_hours=param("sold", 100.1, "server-hour")),
        )


def test_zero_and_dumped_heat():
    thermal = simulate_scenario(scenario(demand=0, on=False))
    result = evaluate(
        thermal,
        Economics(
            (price(),),
            sold_server_hours=param("sold", 0, "server-hour"),
            compute_price=param("price", 0, "CHF/server-hour"),
        ),
    )
    assert result.electricity_cost_chf.value == 0
    assert result.compute_income_chf.value == 0
    assert result.useful_heat_value_chf.value == 0
    assert "zero" in result.case_break_even_chf_per_server_hour.reason
    dumped = evaluate(simulate_scenario(scenario(demand=0)), Economics((price(),)))
    assert dumped.dumped_heat_kwh == pytest.approx(0.8)
    assert dumped.useful_heat_value_chf.value == 0


def test_capex_service_scaling_bracket_and_annualization():
    thermal = simulate_scenario(
        scenario(hours=8760, quantity=2, racks=3, start=START - timedelta(hours=1))
    )
    inputs = Economics(
        (price(),),
        hardware=(
            CostLine(param("rack", 100, "CHF/rack"), "rack"),
            CostLine(param("fixed", 50, "CHF"), "scenario"),
        ),
        installation=(CostLine(param("installation", 20, "CHF/site"), "site"),),
        service=(
            CostLine(param("service", 10, "CHF/rack/year"), "rack"),
            CostLine(param("tier", 5, "CHF/rack/year"), "rack", 6, 10),
        ),
        other_annual_opex=(),
        lifetime_years=param("life", 5, "year"),
        discount_rate=param("discount", 0, "dimensionless"),
        sold_server_hours=param("sold", 100, "server-hour"),
        compute_price=param("compute", 2, "CHF/server-hour"),
    )
    result = evaluate(thermal, inputs)
    assert result.annual
    assert result.hardware_capex_chf.value == 650
    assert result.installation_capex_chf.value == 40
    assert result.capex_chf.value == 690
    assert result.annualized_capex_chf.value == 138
    assert result.service_cost_chf.value == 90
    assert result.compute_income_chf.value == 200
    assert result.rack_hours.value == 52560
    assert result.electricity_cost_chf.value == 13140
    assert result.useful_heat_value_chf.value == pytest.approx(0.2)
    assert result.full_cost_break_even_chf_per_server_hour.value == pytest.approx(133.678)
    assert result.case_break_even_chf_per_server_hour.value == pytest.approx(
        (result.electricity_cost_chf.value - result.useful_heat_value_chf.value) / 100
    )
    assert result.full_cost_break_even_chf_per_server_hour.value == pytest.approx(
        (138 + result.electricity_cost_chf.value + 90 - result.useful_heat_value_chf.value) / 100
    )
    positive = evaluate(
        thermal, replace(inputs, discount_rate=param("rate", 0.05, "dimensionless"))
    )
    assert positive.annualized_capex_chf.value == pytest.approx(690 * 0.05 / (1 - 1.05**-5))


def test_site_local_storage_and_no_double_count():
    first = scenario(demand=0, storage=1).sites[0]
    interval = first.demand.points[0].interval
    pool_demand = ThermalDemandSeries("pool", (DemandPoint(interval, 2),), SOURCE)
    pool = SiteGroup("pool", "pool", 1, pool_demand, (), 0, 0)
    result = evaluate(
        simulate_scenario(Scenario((first, pool))), Economics((price(), price("pool")))
    )
    assert result.useful_heat_value_chf.value == 0
    assert result.backup_heat_kwh == 2
    assert result.backup_cost_chf.value == pytest.approx(0.2)
    assert result.dumped_heat_kwh == 0
    unknown = evaluate(
        simulate_scenario(scenario(demand=1, initial=1, storage=1, on=False)), Economics((price(),))
    )
    assert unknown.useful_heat_value_chf.value is None
    assert "origin unknown" in unknown.useful_heat_value_chf.reason


def test_time_dependent_tariffs_and_mismatch():
    p = price()
    interval = scenario().sites[0].demand.points[0].interval
    tariff = (RatePoint(interval, param("rate", 0.4, "CHF/kWh")),)
    result = evaluate(simulate_scenario(scenario()), Economics((replace(p, electricity=tariff),)))
    assert result.electricity_cost_chf.value == 0.4
    with pytest.raises(ValueError, match="interval mismatch"):
        bad = (RatePoint(Interval(START, START + timedelta(hours=2)), tariff[0].rate),)
        evaluate(simulate_scenario(scenario()), Economics((replace(p, electricity=bad),)))


def test_m3_concurrent_work_uses_rack_union():
    case = scenario(hours=1, demand=2, on=False)
    rack = ComputeRack("r", "home", RACK, 2, 2)
    jobs = tuple(
        Job(name, "synthetic", START, START + timedelta(hours=1), 900, 1, ("home",), True)
        for name in ("a", "b")
    )
    integrated = schedule(case, jobs, (rack,)).integrated
    result = evaluate(
        integrated, Economics((price(),), sold_server_hours=param("sold", 0.25, "server-hour"))
    )
    assert result.rack_hours.value == pytest.approx(0.25)
    with pytest.raises(ValueError, match="exceed"):
        evaluate(
            integrated, Economics((price(),), sold_server_hours=param("sold", 0.5, "server-hour"))
        )


def test_heat_revenue_not_double_counted_and_unknown_tariffs():
    thermal = simulate_scenario(scenario())
    inputs = Economics((replace(price(), heat_mode="revenue"),))
    result = evaluate(thermal, inputs)
    assert result.avoided_heat_cost_chf.value == 0
    assert result.heat_revenue_chf.value == pytest.approx(0.08)
    missing = evaluate(thermal, Economics(()))
    assert "electricity tariff missing" in missing.electricity_cost_chf.reason
    assert "heat value missing" in missing.useful_heat_value_chf.reason


def test_extensible_parameter_groups_preserve_missing_and_provenance():
    tariff = param("electricity_price:home", 0.25, "CHF/kWh")
    hardware = param("per_rack", 120, "CHF/rack")
    zero = Parameter(
        "service_no_costs",
        True,
        "boolean",
        "scenario",
        provenance=Provenance("explicit synthetic zero"),
    )
    groups = (
        ParameterGroup("energy_costs", (tariff,)),
        ParameterGroup("hardware_costs", (hardware,)),
        ParameterGroup("running_service_costs", (zero,)),
        ParameterGroup("unrelated_future_group", ()),
    )
    inputs = economics_from_groups(groups, ("home",))
    assert inputs.site_prices[0].electricity is tariff
    assert inputs.hardware[0].price is hardware
    assert inputs.service == ()
    assert inputs.other_annual_opex is None
    assert inputs.installation is None


def test_annual_cash_flow_does_not_double_count_avoided_heat():
    thermal = simulate_scenario(scenario(hours=8760, demand=100, start=START - timedelta(hours=1)))
    inputs = Economics(
        (price(),),
        hardware=(),
        installation=(),
        service=(),
        other_annual_opex=(),
        lifetime_years=param("life", 5, "year"),
        discount_rate=param("rate", 0, "dimensionless"),
        sold_server_hours=param("sold", 100, "server-hour"),
        compute_price=param("price", 1, "CHF/server-hour"),
    )
    result = evaluate(thermal, inputs)
    assert result.net_cash_contribution_chf.value == pytest.approx(
        100 - result.electricity_cost_chf.value - result.backup_cost_chf.value
    )
    assert result.annualized_total_cost_chf.value == pytest.approx(
        result.electricity_cost_chf.value + result.backup_cost_chf.value - 100
    )


def test_stored_heat_only_valued_at_discharge():
    intervals = (
        Interval(START, START + timedelta(hours=1)),
        Interval(START + timedelta(hours=1), START + timedelta(hours=2)),
    )
    demand = ThermalDemandSeries(
        "home", (DemandPoint(intervals[0], 0), DemandPoint(intervals[1], 0.4)), SOURCE
    )
    group = RackGroup(
        "r", RACK, 1, (OperationPoint(intervals[0], True), OperationPoint(intervals[1], False))
    )
    site = SiteGroup("home", "house", 1, demand, (group,), 1, 0)
    result = evaluate(simulate_scenario(Scenario((site,))), Economics((price(),)))
    assert result.useful_heat_kwh.value == pytest.approx(0.4)
    assert result.useful_heat_value_chf.value == pytest.approx(0.04)


def test_observed_rack_union_and_inactive_inventory():
    case = scenario(hours=1, demand=2, on=False, racks=2)
    first = ComputeRack("first", "home", RACK, 1, 1)
    idle = ComputeRack("idle", "home", RACK, 1, 1)
    spans = (
        RackOnInterval(first, START, START + timedelta(minutes=30)),
        RackOnInterval(first, START + timedelta(minutes=15), START + timedelta(minutes=45)),
    )
    thermal = simulate_rack_intervals(case, (first, idle), spans)
    inputs = Economics((price(),), sold_server_hours=param("sold", 0.75, "server-hour"))
    missing = evaluate(thermal, inputs, observed_intervals=spans)
    assert missing.rack_hours.value is None
    result = evaluate(thermal, inputs, observed_intervals=spans, observed_racks=(first, idle))
    assert result.rack_hours.value == pytest.approx(0.75)
    assert result.electricity_cost_chf.value == pytest.approx(0.75 * 0.25)
    assert result.sold_server_hours.classification == "configured"


def test_case_break_even_can_be_negative():
    high_heat = replace(price(), heat=param("heat", 1, "CHF/kWh"))
    result = evaluate(
        simulate_scenario(scenario()),
        Economics((high_heat,), sold_server_hours=param("sold", 1, "server-hour")),
    )
    assert result.case_break_even_chf_per_server_hour.value == pytest.approx(-0.55)


def test_absolute_full_cost_break_even_includes_backup_with_heat_revenue():
    thermal = simulate_scenario(scenario(hours=8760, demand=1, start=START - timedelta(hours=1)))
    inputs = Economics(
        (replace(price(), heat_mode="revenue"),),
        hardware=(),
        installation=(),
        service=(),
        other_annual_opex=(),
        lifetime_years=param("life", 5, "year"),
        discount_rate=param("rate", 0, "dimensionless"),
        sold_server_hours=param("sold", 100, "server-hour"),
    )
    result = evaluate(thermal, inputs)
    assert result.full_cost_break_even_chf_per_server_hour.value == pytest.approx(
        (
            result.electricity_cost_chf.value
            + result.backup_cost_chf.value
            - result.heat_revenue_chf.value
        )
        / 100
    )
