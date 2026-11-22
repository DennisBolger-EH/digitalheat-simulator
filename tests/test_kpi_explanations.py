from dataclasses import replace

import pytest

from digitalheat_simulator.application.dashboard import (
    Configuration,
    run_optimization,
    run_simulation,
)
from digitalheat_simulator.application.kpi_explanations import (
    chart_explanations,
    not_calculated,
    optimization_explanation,
    optimization_explanations,
    simulation_explanations,
    workload_explanations,
)
from digitalheat_simulator.application.scenario_bundle import BundleScenario, ScenarioBundle
from digitalheat_simulator.config.scenario_csv import load_default
from digitalheat_simulator.finance.model import RatePoint, evaluate
from digitalheat_simulator.ui.kpi_inventory import (
    DISPLAYED_BY_SURFACE,
    PRIMARY_CARDS,
    STORAGE_CHART_SERIES,
    THERMAL_CHART_SERIES,
)
from digitalheat_simulator.ui.main import _clear_results, _show
from digitalheat_simulator.ui.plots import candidates_figure, storage_figure, thermal_figure


@pytest.fixture(scope="module")
def reference():
    return run_simulation(Configuration())


def test_reference_explanations_use_result_and_provenance(reference):
    explanations = simulation_explanations(reference)
    coverage = explanations["heat_coverage"]
    assert coverage.result == pytest.approx(reference.evaluation.metrics.heat_coverage * 100)
    assert coverage.result_unit == "%"
    assert coverage.inputs[0].value == pytest.approx(6105)
    assert coverage.inputs[1].value == pytest.approx(31231.015625)
    assert "Useful server heat / total thermal demand" in coverage.formula
    electricity = explanations["electricity_cost"]
    assert electricity.result == pytest.approx(2912.7)
    assert "0.3325" in electricity.format()
    assert "ElCom" in electricity.format()
    assert "access date: unknown" in electricity.format()
    heat = explanations["heat_value"]
    assert heat.result == pytest.approx(811.965)
    assert "0.133" in heat.format()


def test_unavailable_and_case_exclusion(reference):
    explanations = simulation_explanations(reference)
    income = explanations["compute_income"]
    assert income.result is None
    assert income.classification == "Unavailable"
    assert "sold server-hours missing" in income.notes
    assert "compute sale price missing" in income.notes
    case = explanations["case_break_even"]
    assert "CAPEX and service costs are not included" in case.notes
    assert "sold server-hours" in case.formula
    assert "sold server-hours" in explanations["full_break_even"].formula


def test_annualized_capex_formula_branches(reference):
    metrics = reference.evaluation.metrics
    economics = metrics.economics
    finance = economics.inputs
    rate = finance.site_prices[0].electricity
    lifetime = replace(rate, identifier="lifetime", value=10, unit="year")
    for r, expected in ((0.0, "CAPEX / lifetime"), (0.05, "CAPEX × rate")):
        discount = replace(rate, identifier="discount", value=r, unit="dimensionless")
        altered = replace(
            economics, inputs=replace(finance, lifetime_years=lifetime, discount_rate=discount)
        )
        evaluation = replace(reference.evaluation, metrics=replace(metrics, economics=altered))
        explanation = simulation_explanations(replace(reference, evaluation=evaluation))[
            "annualized_capex"
        ]
        assert expected in explanation.formula


def test_changed_run_has_changed_explanation(reference):
    config = Configuration()
    config.set("racks", 2)
    updated = run_simulation(config)
    first = simulation_explanations(reference)["electricity_cost"]
    second = simulation_explanations(updated)["electricity_cost"]
    assert first.result == pytest.approx(2912.7)
    assert second.result == pytest.approx(5825.4)
    assert first.inputs[0].value == pytest.approx(8760)
    assert second.inputs[0].value == pytest.approx(17520)


def test_optimization_and_workload_explanations():
    search = run_optimization(Configuration(mode="synthetic", budget=25))
    explanation = optimization_explanation(search)
    assert explanation.result == search.best.objective_value
    assert search.result_label in explanation.notes
    assert explanation.inputs[2].value == search.evaluated_count
    data = {
        "active_seconds": 3600,
        "power": {"electrical_kw": 1, "gross_thermal_kw": 1, "recovery_efficiency": 0.8},
        "energy": {"electrical_kwh_estimated": 1, "recoverable_heat_kwh_derived": 0.8},
    }
    work = workload_explanations(data)
    assert work["workload_electricity"].classification == "Estimated"
    assert work["workload_electricity"].result == 1
    assert "not physically measured" in work["workload_electricity"].notes
    assert work["workload_heat"].result == pytest.approx(0.8)


def test_displayed_identifiers_are_explained(reference):
    search = run_optimization(Configuration(mode="synthetic", budget=10))
    available = (
        set(simulation_explanations(reference))
        | set(chart_explanations(reference))
        | set(optimization_explanations(search))
        | set(workload_explanations({}))
    )
    displayed = set().union(*DISPLAYED_BY_SURFACE.values())
    assert displayed - available == set()
    assert set(THERMAL_CHART_SERIES) | set(STORAGE_CHART_SERIES) <= displayed
    assert {trace.meta for trace in thermal_figure(reference).data} == set(THERMAL_CHART_SERIES)
    assert {trace.meta for trace in storage_figure(reference).data} == set(STORAGE_CHART_SERIES)
    assert {trace.meta for trace in candidates_figure(search).data} == {"optimization_candidates"}
    assert sum(len(keys) for _, keys in PRIMARY_CARDS) == 9


def test_chart_semantics_and_pre_run(reference):
    chart = chart_explanations(reference)
    assert "demand − direct server heat − storage discharge" in chart["chart_backup"].formula
    assert chart["chart_backup"].result == reference.evaluation.metrics.backup_heat_kwh
    assert "opening storage + charge − discharge" in chart["chart_storage"].formula
    pending = not_calculated("heat_coverage", "Heat coverage")
    assert pending.classification == "Not calculated"
    assert pending.inputs == ()
    assert "Run Simulation" in pending.format()
    assert "Unavailable" not in pending.format()
    assert _show(0, "kWh") == "0 kWh"
    assert _show(None, "kWh").startswith("Unavailable")


def test_switching_clears_run_and_explanations(reference):
    a = Configuration()
    b = Configuration()
    b.set("racks", 2)
    bundle = ScenarioBundle(
        2,
        "test",
        None,
        {
            "a": BundleScenario("a", "Scenario A", a),
            "b": BundleScenario("b", "Scenario B", b),
        },
        "a",
    )
    results = {"simulation": reference, "optimization": object()}
    identities = {"simulation": ("a", "Scenario A"), "optimization": ("a", "Scenario A")}
    assert simulation_explanations(results["simulation"])[
        "electricity_cost"
    ].result == pytest.approx(2912.7)
    bundle.select("b")
    _clear_results(results, identities)
    assert all(value is None for value in results.values())
    assert all(value is None for value in identities.values())
    assert not_calculated("electricity_cost", "Electricity cost").classification == "Not calculated"
    results["simulation"] = run_simulation(bundle.active.configuration)
    assert simulation_explanations(results["simulation"])[
        "electricity_cost"
    ].result == pytest.approx(5825.4)
    bundle.active.configuration.set("racks", 3)
    results["simulation"] = run_simulation(bundle.active.configuration)
    assert simulation_explanations(results["simulation"])[
        "electricity_cost"
    ].result == pytest.approx(8738.1)
    bundle.select("a")
    _clear_results(results, identities)
    assert results["simulation"] is None
    assert "5,825" not in not_calculated("electricity_cost", "Electricity cost").format()


def test_workload_measurement_and_estimates():
    pending = workload_explanations({"status": "Ready"})
    assert all(item.classification == "Not calculated" for item in pending.values())
    data = {
        "progress": 5,
        "replicates": 10,
        "active_seconds": 3600,
        "decision": {"run": True, "opportunity_kwh": 1, "estimated_remaining_seconds": 20},
        "power": {"electrical_kw": 1, "gross_thermal_kw": 2, "recovery_efficiency": 0.8},
        "energy": {
            "electrical_kwh_estimated": 1,
            "gross_heat_kwh_estimated": 2,
            "recoverable_heat_kwh_derived": 1.6,
        },
    }
    work = workload_explanations(data)
    assert work["workload_progress"].classification == "Measured"
    assert work["workload_runtime"].classification == "Measured"
    assert work["workload_power"].result == 1
    assert work["workload_gross_heat"].classification == "Estimated"
    assert work["workload_gross_heat"].result == 2
    assert work["workload_heat"].result == 1.6
    assert work["workload_checkpoint"].classification == "Unavailable"


def test_full_finance_and_discount_rate_use_actual_run():
    config = load_default("complete")
    for discount in (0, 0.05):
        config.set("discount_rate", discount)
        result = run_simulation(config)
        economics = result.evaluation.metrics.economics
        explanations = simulation_explanations(result)
        assert explanations["annualized_capex"].result == economics.annualized_capex_chf.value
        assert ("CAPEX / lifetime" in explanations["annualized_capex"].formula) == (discount == 0)
        assert (
            explanations["case_break_even"].result
            == economics.case_break_even_chf_per_server_hour.value
        )
        assert (
            explanations["full_break_even"].result
            == economics.full_cost_break_even_chf_per_server_hour.value
        )
        assert "avoided" in explanations["full_break_even"].notes


def test_interval_tariffs_and_uncertain_opening_storage(reference):
    economics = reference.evaluation.metrics.economics
    original = economics.inputs.site_prices[0]
    points = reference.thermal.intervals
    tariff = tuple(
        RatePoint(point.interval, replace(original.electricity, value=0.1 if index % 2 else 0.4))
        for index, point in enumerate(points)
    )
    inputs = replace(economics.inputs, site_prices=(replace(original, electricity=tariff),))
    actual = evaluate(reference.thermal, inputs)
    metrics = replace(reference.evaluation.metrics, economics=actual)
    updated = replace(reference, evaluation=replace(reference.evaluation, metrics=metrics))
    explained = simulation_explanations(updated)["electricity_cost"]
    assert explained.result == actual.electricity_cost_chf.value
    assert "0.1 to 0.4" in explained.format()
    assert "interval energy × interval tariff" in explained.calculation
    config = Configuration()
    config.set("initial", 10)
    unknown = simulation_explanations(run_simulation(config))
    assert unknown["useful_heat"].result is None
    assert "origin unknown" in unknown["useful_heat"].notes
    assert unknown["heat_value"].inputs[0].value is None
