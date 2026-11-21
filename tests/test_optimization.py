from dataclasses import replace
from datetime import timedelta

import pytest

from digitalheat_simulator.application.optimization import Capacity, ScenarioEvaluator
from digitalheat_simulator.application.optimization_demo import example, parameter
from digitalheat_simulator.domain.compute import Job
from digitalheat_simulator.domain.parameters import ParameterGroup
from digitalheat_simulator.domain.scenario import (
    DemandPoint,
    OperationPoint,
    Scenario,
    SiteGroup,
    ThermalDemandSeries,
)
from digitalheat_simulator.finance.model import CostLine, Economics, SitePrices
from digitalheat_simulator.optimization.search import search


def values(candidate):
    return {(g.identifier, p.identifier): p.value for g in candidate.groups for p in g.parameters}


def test_exhaustive_global_multi_group_and_deterministic():
    scenario, economics, groups = example()
    first = search(groups, ScenarioEvaluator(scenario, economics), "economic")
    second = search(groups, ScenarioEvaluator(scenario, economics), "economic")
    assert first == second
    assert (
        first.exhaustive and first.grid_size == first.evaluated_count == first.feasible_count == 625
    )
    assert first.rejected_count == 0
    best = values(first.best)
    assert best["quantities", "rack_count:house:rack"] == 1
    assert best["hardware_costs", "per_rack"] == 100
    assert best["compute_income", "price_per_server_hour"] == 4
    assert best["storage", "capacity_kwh:house"] == 4
    assert first.best.objective_value == min(c.objective_value for c in first.candidates)
    assert all(
        p.provenance.source.startswith("synthetic") for g in first.best.groups for p in g.parameters
    )
    assert all(
        "explored grid candidate" in p.provenance.transformation
        for g in first.best.groups
        for p in g.parameters
    )


def test_group_only_fixed_and_one_variable():
    scenario, economics, groups = example()
    result = search(
        groups, ScenarioEvaluator(scenario, economics), "economic", group="hardware_costs"
    )
    assert result.evaluated_count == 5
    assert values(result.best)["hardware_costs", "per_rack"] == 100
    assert values(result.best)["compute_income", "price_per_server_hour"] == 0
    assert len(result.fixed_parameters) == 3


def test_thermal_lexicographic_and_ties():
    scenario, economics, groups = example()
    result = search(groups, ScenarioEvaluator(scenario, economics), "thermal")
    expected = min((-c.objective_value[0], c.objective_value[1]) for c in result.candidates)
    assert (-result.best.objective_value[0], result.best.objective_value[1]) == expected
    chosen = values(result.best)
    assert chosen["hardware_costs", "per_rack"] == 100
    assert chosen["compute_income", "price_per_server_hour"] == 0
    assert result.best.evaluation.metrics.heat_coverage is not None


def test_missing_economics_rejected_not_zero_and_thermal_independent():
    scenario, _, groups = example()
    missing = Economics(())
    result = search(groups[:2], ScenarioEvaluator(scenario, missing), "economic")
    assert result.best is None and result.rejected_count == 25
    assert "missing" in result.candidates[0].rejection_reasons[0]
    thermal = search(groups[:2], ScenarioEvaluator(scenario, missing), "thermal")
    assert thermal.best is not None


def test_quantity_and_infeasible_sold_hours():
    scenario, economics, groups = example()
    zero = replace(groups[0].parameters[0], value=0, minimum=0, maximum=1)
    result = search(
        (ParameterGroup("quantities", (zero,)),), ScenarioEvaluator(scenario, economics), "thermal"
    )
    assert result.evaluated_count == 2
    assert result.rejected_count == 1
    assert "sold server-hours exceed" in result.candidates[0].rejection_reasons[0]
    assert isinstance(values(result.best)["quantities", "rack_count:house:rack"], int)


def test_sampled_search_stable_and_budgeted():
    scenario, economics, groups = example()
    a = search(groups, ScenarioEvaluator(scenario, economics), "economic", budget=40)
    b = search(groups, ScenarioEvaluator(scenario, economics), "economic", budget=40)
    assert a == b and a.evaluated_count <= 40 and not a.exhaustive
    assert a.result_label == "best evaluated candidate"


def test_grid_metadata_endpoints_and_fixed():
    scenario, economics, groups = example()
    p = replace(groups[1].parameters[0], maximum=3.5, step=2)
    disabled = replace(groups[2].parameters[0], enabled=False)
    result = search(
        (ParameterGroup("storage", (p,)), ParameterGroup("hardware_costs", (disabled,))),
        ScenarioEvaluator(scenario, economics),
        "thermal",
    )
    assert [values(c)["storage", "capacity_kwh:house"] for c in result.candidates] == [0, 2]
    bad = replace(groups[0].parameters[0], step=0.5)
    with pytest.raises(ValueError, match="integral"):
        search(
            (ParameterGroup("quantities", (bad,)),),
            ScenarioEvaluator(scenario, economics),
            "thermal",
        )


def test_locality_and_unknown_storage():
    scenario, economics, _ = example()
    house = scenario.sites[0]
    pool_demand = ThermalDemandSeries(
        "pool",
        tuple(DemandPoint(p.interval, 100) for p in house.demand.points),
        house.demand.provenance,
    )
    pool = SiteGroup("pool", "pool", 1, pool_demand, (), 0, 0)
    result = search((), ScenarioEvaluator(Scenario((house, pool)), economics), "thermal")
    metrics = result.best.evaluation.metrics
    assert metrics.backup_heat_kwh >= 200
    unknown = replace(
        house,
        initial_storage_kwh=1,
        storage_capacity_kwh=1,
        racks=tuple(
            replace(r, operation=tuple(replace(o, on=False) for o in r.operation))
            for r in house.racks
        ),
    )
    result = search(
        (),
        ScenarioEvaluator(Scenario((unknown,)), replace(economics, sold_server_hours=None)),
        "thermal",
    )
    assert result.best is None and "origin unknown" in result.candidates[0].rejection_reasons[0]


def test_scheduler_integration_and_deadline_rejection():
    scenario, economics, _ = example()
    site = scenario.sites[0]
    racks = tuple(
        replace(r, operation=tuple(OperationPoint(o.interval, False) for o in r.operation))
        for r in site.racks
    )
    scenario = Scenario((replace(site, racks=racks, quantity=2),))
    start = site.demand.points[0].interval.start
    job = Job("job", "synthetic", start, start + timedelta(hours=1), 3600, 1, ("house",), True)
    evaluator = ScenarioEvaluator(
        scenario,
        replace(economics, sold_server_hours=None),
        jobs=(job,),
        capacities=(Capacity("house", "rack", 1, 1),),
    )
    result = search((), evaluator, "thermal")
    assert result.best is not None
    metrics = result.best.evaluation.metrics
    assert len(metrics.scenario.sites) == 2
    assert metrics.delivered_work_tflop == pytest.approx(3600)
    assert metrics.completed_jobs == 1 and metrics.missed_deadlines == 0
    impossible = replace(job, required_work_tflop=7200)
    result = search(
        (),
        ScenarioEvaluator(
            scenario,
            replace(economics, sold_server_hours=None),
            jobs=(impossible,),
            capacities=(Capacity("house", "rack", 1, 1),),
        ),
        "thermal",
    )
    assert result.best is None
    assert any("deadline" in reason for reason in result.candidates[0].rejection_reasons)


def test_zero_site_count_and_local_price_binding():
    scenario, economics, _ = example()
    house = scenario.sites[0]
    pool = replace(house, identifier="pool", consumer_kind="pool", racks=(), quantity=1)
    scenario = Scenario((house, pool))
    economics = replace(
        economics,
        site_prices=economics.site_prices
        + (SitePrices("pool", parameter("electricity", 5, "CHF/kWh")),),
    )
    count = parameter("site_count:pool", 0, "count", low=0, high=1, step=1, integer=True)
    result = search(
        (ParameterGroup("quantities", (count,)),),
        ScenarioEvaluator(scenario, economics),
        "thermal",
    )
    assert result.feasible_count == 2
    assert len(result.candidates[0].evaluation.metrics.scenario.sites) == 1
    assert len(result.candidates[1].evaluation.metrics.scenario.sites) == 2


def test_disabled_economic_parameter_uses_explicit_base_not_missing_or_zero():
    scenario, economics, groups = example()
    base = replace(
        economics,
        hardware=(CostLine(parameter("rack", 77, "CHF/rack"), "rack"),),
        compute_price=parameter("price", 1, "CHF/server-hour"),
    )
    disabled = replace(groups[2].parameters[0], enabled=False)
    result = search(
        (ParameterGroup("hardware_costs", (disabled,)),),
        ScenarioEvaluator(scenario, base),
        "economic",
    )
    assert result.best.evaluation.metrics.economics.hardware_capex_chf.value == 77


def test_sampled_search_continues_when_coarse_candidates_are_infeasible():
    scenario, economics, groups = example()
    low = replace(groups[0].parameters[0], value=0, minimum=0, maximum=4)
    result = search(
        (ParameterGroup("quantities", (low,)),),
        ScenarioEvaluator(
            scenario,
            replace(economics, sold_server_hours=parameter("sold", 20000, "server-hour")),
        ),
        "thermal",
        budget=3,
    )
    assert result.evaluated_count == 3
    assert result.best is not None
    assert values(result.best)["quantities", "rack_count:house:rack"] == 3


def test_scheduled_cache_key_includes_workload():
    scenario, economics, _ = example()
    site = scenario.sites[0]
    racks = tuple(
        replace(r, operation=tuple(replace(o, on=False) for o in r.operation)) for r in site.racks
    )
    scenario = Scenario((replace(site, racks=racks),))
    start = site.demand.points[0].interval.start
    job = Job("job", "synthetic", start, start + timedelta(hours=1), 3600, 1, ("house",), True)
    evaluator = ScenarioEvaluator(
        scenario,
        replace(economics, sold_server_hours=None),
        jobs=(job,),
        capacities=(Capacity("house", "rack", 1, 1),),
    )
    first = search((), evaluator, "thermal")
    evaluator.jobs = (replace(job, required_work_tflop=1800),)
    second = search((), evaluator, "thermal")
    assert first.best.evaluation.metrics.delivered_work_tflop == pytest.approx(3600)
    assert second.best.evaluation.metrics.delivered_work_tflop == pytest.approx(1800)
    assert evaluator.cache_hits == 0
