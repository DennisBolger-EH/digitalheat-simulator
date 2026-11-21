import json
from dataclasses import replace

import pytest

from digitalheat_simulator.application import workload_view
from digitalheat_simulator.application.dashboard import (
    Configuration,
    prepare,
    run_optimization,
    run_simulation,
)
from digitalheat_simulator.finance.model import Amount
from digitalheat_simulator.ui.main import _amount, _show
from digitalheat_simulator.ui.plots import candidates_figure, storage_figure, thermal_figure


@pytest.fixture(scope="module")
def reference():
    return run_simulation(Configuration())


def test_reference_kpis_and_missing_reasons(reference):
    metrics = reference.evaluation.metrics
    assert metrics.useful_heat_kwh == pytest.approx(6105)
    assert metrics.backup_heat_kwh == pytest.approx(25126.015625)
    assert metrics.dumped_heat_kwh == pytest.approx(903)
    assert metrics.electricity_kwh == pytest.approx(8760)
    assert metrics.economics.electricity_cost_chf.value == pytest.approx(2912.7)
    assert "hardware inputs missing" in metrics.economics.annualized_total_cost_chf.reason
    assert metrics.delivered_work_tflop is None
    assert _amount(Amount.missing("not supplied"), "CHF") == "Unavailable — not supplied"
    assert _show(0, "kWh") == "0 kWh"


def test_dirty_binding_provenance_and_validation():
    config = Configuration()
    assert not config.dirty
    config.set("racks", 2.0)
    assert config.dirty and config.revision == 1
    scenario, _, groups, _ = prepare(config)
    assert scenario.sites[0].racks[0].quantity == 2
    rack = next(p for g in groups for p in g.parameters if p.identifier == "rack_count:house:rack")
    assert rack.value == 2 and rack.provenance.source == "user input"
    tariff = next(
        p for g in groups for p in g.parameters if p.identifier == "electricity_price:house"
    )
    assert "ElCom" in tariff.provenance.source
    config.set("storage", -1)
    with pytest.raises(ValueError, match="Storage capacity.*nonnegative"):
        run_simulation(config)


def test_pool_requires_supplied_profile_and_no_cross_site_heat():
    config = Configuration()
    config.set("pools", 1)
    with pytest.raises(ValueError, match="supplied hourly profile"):
        run_simulation(config)
    config.pool_source = "user supplied synthetic test"
    config.pool_values = (1,) * 8760
    result = run_simulation(config)
    pool = next(site for site in result.thermal.sites if site.site.identifier == "pool")
    assert sum(flow.backup_heat_kwh for flow in pool.per_site_flows) == 8760
    assert sum(flow.recoverable_heat_kwh for flow in pool.per_site_flows) == 0
    assert (
        "pool electricity tariff missing"
        in result.evaluation.metrics.economics.electricity_cost_chf.reason
    )


def test_configured_capacity_is_not_compute_work():
    config = Configuration()
    config.set("racks", 2)
    config.set("capacity", 5)
    result = run_simulation(config)
    assert result.installed_capacity_tflop_per_s == 10
    assert result.evaluation.metrics.delivered_work_tflop is None
    assert result.evaluation.metrics.compute_utilization is None


def test_synthetic_optimization_exhaustive_and_sampled():
    config = Configuration(mode="synthetic", budget=625)
    result = run_optimization(config)
    assert result.exhaustive
    assert result.feasible_count == 625
    assert result.best.objective_value == pytest.approx(1948.16)
    assert result.result_label == "optimal within declared finite grid"
    config.budget = 10
    config.objective = "thermal"
    result = run_optimization(config)
    assert not result.exhaustive and result.evaluated_count == 10
    assert result.result_label == "best evaluated candidate"
    assert len(candidates_figure(result).data[0].x) == result.feasible_count
    config.budget = 626
    with pytest.raises(ValueError, match="budget"):
        run_optimization(config)


def test_synthetic_changes_and_ranges_are_shared():
    config = Configuration(mode="synthetic")
    key = "synthetic:quantities:rack_count:house:rack"
    config.set(key, 2.0)
    config.ranges[("quantities", "rack_count:house:rack")] = (True, 1, 3, 1)
    _, _, groups, _ = prepare(config)
    p = groups[0].parameters[0]
    assert p.value == 2 and p.provenance.source.startswith("user input")
    assert p.maximum == 3
    config.ranges[("quantities", "rack_count:house:rack")] = (True, None, 3, 1)
    with pytest.raises(ValueError, match="minimum, maximum and step"):
        prepare(config)


def test_plot_data(reference):
    assert len(thermal_figure(reference).data[0].x) == 8760
    assert len(thermal_figure(reference, 1).data[0].x) == 744
    assert len(thermal_figure(reference, 7).data[0].x) == 744
    assert len(storage_figure(reference).data[0].x) == 8760


def test_workload_status_mapping(tmp_path, monkeypatch):
    path = tmp_path / "journal.json"
    data = {
        "version": 1,
        "execution_id": "id",
        "status": "completed",
        "identity": {"replicates": 100},
        "progress_measured": 100,
        "active_ns_measured": 3600000000000,
        "power_assumptions": {
            "electrical_kw": 1,
            "gross_thermal_kw": 1,
            "recovery_efficiency": 0.8,
        },
        "events": [{"kind": "scheduler decision", "run": True, "opportunity_kwh": 1}],
        "checkpoint": {"progress": 50},
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    service = workload_view.Demonstration(tmp_path)
    service.journal = path
    snapshot = service.snapshot()
    assert snapshot["progress"] == 100
    assert snapshot["decision"]["run"]
    assert snapshot["energy"]["electrical_kwh_estimated"] == 1
    assert snapshot["energy"]["recoverable_heat_kwh_derived"] == pytest.approx(0.8)
    assert snapshot["checkpoint"]["progress"] == 50

    def fake_run(weather, root, replicates, pre_pause, paused_seconds, on_created):
        on_created(path)
        return path

    monkeypatch.setattr(workload_view.real_demo, "run", fake_run)
    service.run()
    assert service.status == "Completed"


def test_missing_pool_price_and_real_economic_input_is_not_synthetic(reference):
    economics = reference.evaluation.metrics.economics
    assert economics.inputs.site_prices[0].electricity.value == 0.3325
    assert economics.compute_income_chf.value is None
    assert replace(economics.inputs, hardware=()).hardware == ()
