import csv
import io
from dataclasses import replace

import pytest

from digitalheat_simulator.application.dashboard import run_optimization, run_simulation
from digitalheat_simulator.config.bundle_csv import (
    BUNDLE_COLUMNS,
    export_bundle,
    import_bundle,
)
from digitalheat_simulator.config.scenario_csv import DEFAULTS, export_scenario, load_default


@pytest.fixture
def bundle():
    text = (DEFAULTS / "multi-scenario-template.csv").read_text(encoding="utf-8")
    return import_bundle(text, "template.csv")


def mutate(text, predicate, **changes):
    reader = csv.DictReader(io.StringIO(text, newline=""))
    rows = list(reader)
    next(row for row in rows if predicate(row)).update(changes)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=BUNDLE_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def test_template_contains_independent_complete_scenarios(bundle):
    assert list(bundle.scenarios) == ["reference-house", "swimming-pool", "optimization-demo"]
    assert bundle.active.scenario_name == "Reference House"
    assert bundle.scenarios["swimming-pool"].configuration.values["pools"] == 0
    assert bundle.scenarios["optimization-demo"].configuration.mode == "synthetic"
    assert len({id(s.configuration) for s in bundle.scenarios.values()}) == 3


def test_switch_preserves_edits_and_dirty_state(bundle):
    house = bundle.active.configuration
    house.set("storage", 40)
    assert bundle.dirty and bundle.active.dirty
    pool = bundle.select("swimming-pool").configuration
    assert not bundle.active.dirty and pool.values["storage"] == 35
    pool.set("pool_storage", 11)
    bundle.select("optimization-demo")
    assert not bundle.active.dirty
    assert bundle.select("swimming-pool").configuration.values["pool_storage"] == 11
    assert bundle.select("reference-house").configuration.values["storage"] == 40
    bundle.mark_saved()
    assert not bundle.dirty
    house.set("storage", 41)
    assert bundle.active.dirty


def test_active_simulation_and_optimization_are_isolated(bundle):
    result = run_simulation(bundle.active.configuration)
    assert result.evaluation.metrics.useful_heat_kwh == pytest.approx(6105)
    synthetic = bundle.select("optimization-demo").configuration
    synthetic.budget = 10
    result = run_optimization(synthetic)
    assert result.evaluated_count == 10 and not result.exhaustive


def test_bundle_export_round_trip_preserves_values_metadata_and_ranges(bundle):
    pool = bundle.select("swimming-pool").configuration
    pool.set("storage", 39)
    pool.ranges["quantities", "rack_count:house:rack"] = (True, 1, 2, 1)
    pool.mark_dirty()
    text = export_bundle(bundle)
    restored = import_bundle(text, "export.csv")
    assert list(restored.scenarios) == list(bundle.scenarios)
    assert [s.scenario_name for s in restored.scenarios.values()] == [
        s.scenario_name for s in bundle.scenarios.values()
    ]
    for key in bundle.scenarios:
        original = bundle.scenarios[key].configuration
        imported = restored.scenarios[key].configuration
        assert all(imported.values[name] == value for name, value in original.values.items())
        assert imported.ranges == original.ranges
        for name, metadata in original.metadata.items():
            assert imported.metadata[name] == replace(metadata, value=original.values[name])
    assert restored.select("swimming-pool").configuration.values["storage"] == 39
    assert restored.active.configuration.metadata["storage"].provenance.source == "user input"


@pytest.mark.parametrize(
    ("predicate", "changes", "message"),
    [
        (
            lambda r: r["scenario_id"] == "swimming-pool",
            {"scenario_name": "Different"},
            "two different names",
        ),
        (lambda r: r["scenario_id"] == "swimming-pool", {"scenario_id": "INVALID"}, "Scenario ID"),
        (
            lambda r: r["scenario_id"] == "swimming-pool",
            {"scenario_name": "Reference House"},
            "Duplicate scenario name",
        ),
        (
            lambda r: r["scenario_id"] == "swimming-pool" and r["identifier"] == "racks",
            {"value": "1.5"},
            'Scenario "Swimming Pool".*racks.*whole number',
        ),
        (
            lambda r: r["scenario_id"] == "swimming-pool",
            {"version": "3"},
            "unsupported scenario CSV version",
        ),
    ],
)
def test_invalid_bundle_rejected_atomically(bundle, predicate, changes, message):
    text = export_bundle(bundle)
    before = bundle.active.configuration.values.copy()
    with pytest.raises(ValueError, match=message):
        import_bundle(mutate(text, predicate, **changes), "bad.csv")
    assert bundle.active.configuration.values == before
    assert len(bundle.scenarios) == 3


def test_duplicate_parameter_rejected(bundle):
    text = export_bundle(bundle)
    reader = csv.DictReader(io.StringIO(text, newline=""))
    rows = list(reader)
    row = next(
        r for r in rows if r["scenario_id"] == "swimming-pool" and r["identifier"] == "racks"
    )
    rows.append(row)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=BUNDLE_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    with pytest.raises(ValueError, match='Scenario "Swimming Pool".*Duplicate parameter'):
        import_bundle(output.getvalue(), "bad.csv")


def test_version_one_import_and_version_two_export():
    original = load_default("reference")
    bundle = import_bundle(export_scenario(original), "My House 2025.csv")
    assert bundle.format_version == 1
    assert bundle.active_scenario_id == "my-house-2025"
    assert bundle.active.scenario_name == "My House 2025"
    assert import_bundle(export_bundle(bundle), "new.csv").format_version == 2
    with pytest.raises(ValueError):
        import_bundle(
            export_scenario(original).replace(
                ",racks,Racks per house,1,", ",racks,Racks per house,1.5,"
            ),
            "bad.csv",
        )


def test_distinct_optimization_ranges_and_provenance_round_trip(bundle):
    house = bundle.scenarios["reference-house"].configuration
    pool = bundle.scenarios["swimming-pool"].configuration
    house.ranges["quantities", "rack_count:house:rack"] = (True, 1, 2, 1)
    pool.ranges["quantities", "rack_count:house:rack"] = (True, 1, 3, 1)
    pool.set("electricity_price:house", 0.4)
    restored = import_bundle(export_bundle(bundle), "bundle.csv")
    assert restored.scenarios["reference-house"].configuration.ranges[
        "quantities", "rack_count:house:rack"
    ] == (True, 1, 2, 1)
    imported_pool = restored.scenarios["swimming-pool"].configuration
    assert imported_pool.ranges["quantities", "rack_count:house:rack"] == (True, 1, 3, 1)
    assert imported_pool.metadata["electricity_price:house"].provenance.source == "user input"
    assert "ElCom" in (
        restored.scenarios["reference-house"]
        .configuration.metadata["electricity_price:house"]
        .provenance.source
    )


def test_empty_bundle_and_missing_identity_are_rejected(bundle):
    with pytest.raises(ValueError, match="no scenarios"):
        import_bundle(",".join(BUNDLE_COLUMNS) + "\n", "empty.csv")
    text = export_bundle(bundle)
    with pytest.raises(ValueError, match="Scenario ID"):
        import_bundle(mutate(text, lambda r: True, scenario_id=""), "bad.csv")
    with pytest.raises(ValueError, match="requires a name"):
        import_bundle(mutate(text, lambda r: True, scenario_name=""), "bad.csv")
