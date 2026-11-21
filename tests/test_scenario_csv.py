import csv
import io
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from digitalheat_simulator.application.dashboard import (
    Configuration,
    prepare,
    replace_configuration,
    run_simulation,
)
from digitalheat_simulator.config.scenario_csv import (
    COLUMNS,
    DEFAULTS,
    _synthetic_fields,
    export_scenario,
    import_scenario,
    load_default,
)
from digitalheat_simulator.domain.parameters import Parameter, Provenance


def rows(text):
    return list(csv.DictReader(io.StringIO(text)))


def write_rows(items):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(items)
    return output.getvalue()


def changed(text, key, **changes):
    items = rows(text)
    item = next(r for r in items if r["kind"] == "parameter" and r["identifier"] == key)
    item.update(changes)
    return write_rows(items)


def test_export_import_round_trip_with_complete_metadata():
    config = load_default("complete")
    config.metadata["racks"] = Parameter(
        "racks",
        1,
        "integer",
        "scenario",
        "count",
        "My rack count",
        "Example description",
        0,
        4,
        1,
        1,
        (0.5, 1.5),
        True,
        True,
        Provenance("user input", date(2024, 1, 2), date(2024, 2, 3), "rack", "house", "none"),
    )
    text = export_scenario(config)
    imported = import_scenario(text)
    assert imported.values == config.values
    assert imported.ranges == config.ranges
    assert imported.metadata["racks"] == config.metadata["racks"]
    assert imported.objective == config.objective and imported.budget == config.budget
    assert import_scenario(export_scenario(imported)).metadata == imported.metadata
    assert "useful_heat" not in text and "annualized_total_cost" not in text
    scenario, _, groups, _ = prepare(imported)
    rack = next(p for g in groups for p in g.parameters if p.identifier == "rack_count:house:rack")
    assert scenario.sites[0].racks[0].quantity == 1
    assert rack.provenance == config.metadata["racks"].provenance


def test_optional_metadata_and_disabled_input():
    config = load_default("complete")
    item = config.metadata["hardware_costs:per_rack"]
    config.metadata["hardware_costs:per_rack"] = replace(item, enabled=False)
    imported = import_scenario(export_scenario(config))
    assert imported.metadata["hardware_costs:per_rack"].enabled is False
    result = run_simulation(imported)
    assert result.evaluation.metrics.economics.annualized_total_cost_chf.value is None
    imported.set("hardware_costs:per_rack", 12000)
    assert imported.metadata["hardware_costs:per_rack"].enabled is True
    assert imported.metadata["hardware_costs:per_rack"].provenance.source == "user input"


@pytest.mark.parametrize(
    ("identifier", "changes", "message"),
    [
        ("racks", {"value": "1.5"}, "whole number"),
        ("racks", {"value": "-1"}, ">= 0"),
        ("storage", {"value": "nope"}, "valid number"),
        ("storage", {"value": "nan"}, "finite"),
        ("storage", {"unit": "MWh"}, "unit"),
        ("storage", {"data_type": "boolean"}, "data type"),
        ("storage", {"enabled": "yes"}, "true or false"),
        ("storage", {"enabled": "false"}, "cannot be disabled"),
        ("storage", {"optimizable": "true"}, "require minimum"),
        ("storage", {"minimum": "50", "maximum": "10"}, "minimum"),
        ("storage", {"step": "0"}, "step"),
        ("racks", {"minimum": "0.5"}, "whole number"),
        ("racks", {"value": "9007199254740993"}, "safe integer"),
        ("storage", {"uncertainty_min": "1"}, "both uncertainty"),
        ("storage", {"source": ""}, "source"),
    ],
)
def test_invalid_parameter_values_rejected(identifier, changes, message):
    with pytest.raises(ValueError, match=message):
        import_scenario(changed(export_scenario(Configuration()), identifier, **changes))


def test_duplicate_unknown_version_missing_columns_rows_and_result_rejected():
    text = export_scenario(Configuration())
    items = rows(text)
    with pytest.raises(ValueError, match="Duplicate"):
        import_scenario(write_rows(items + [items[0]]))
    with pytest.raises(ValueError, match="Unknown parameter"):
        import_scenario(changed(text, "racks", identifier="useful_heat"))
    altered = rows(text)
    altered[0]["version"] = "2"
    with pytest.raises(ValueError, match="version"):
        import_scenario(write_rows(altered))
    with pytest.raises(ValueError, match="incomplete"):
        import_scenario(write_rows(items[1:]))
    with pytest.raises(ValueError, match="columns"):
        import_scenario(text.replace("identifier,", "bad_identifier,", 1))
    altered = rows(text)
    altered[0]["kind"] = "result"
    with pytest.raises(ValueError, match="Unknown scenario row"):
        import_scenario(write_rows(altered))
    with pytest.raises(ValueError, match="malformed"):
        import_scenario(text + "1,too,few\n")


def test_invalid_import_does_not_change_existing_configuration():
    current = load_default("complete")
    original = export_scenario(current)
    with pytest.raises(ValueError):
        import_scenario(changed(original, "racks", value="1.1"))
    assert export_scenario(current) == original
    assert not current.dirty


def test_changed_reference_value_must_not_retain_reference_provenance():
    text = export_scenario(load_default("reference"))
    with pytest.raises(ValueError, match="cannot retain the reference provenance"):
        import_scenario(changed(text, "electricity_price:house", value="0.4"))


def test_active_range_requires_an_applicable_parameter():
    config = load_default("reference")
    config.ranges[("compute_income", "price_per_server_hour")] = (True, 1, 2, 1)
    with pytest.raises(ValueError, match="active range is not applicable"):
        import_scenario(export_scenario(config))


def test_import_updates_shared_configuration_and_ranges_without_running(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("scenario application must not run a simulation or optimization")

    monkeypatch.setattr("digitalheat_simulator.application.dashboard.run_simulation", forbidden)
    monkeypatch.setattr("digitalheat_simulator.application.dashboard.run_optimization", forbidden)
    current = Configuration()
    current.set("storage", 42)
    imported = import_scenario(export_scenario(load_default("complete")))
    identity = id(current)
    replace_configuration(current, imported)
    assert id(current) == identity
    assert current.values["storage"] == 35
    assert current.values["hardware_costs:per_rack"] == 12000
    assert current.ranges[("quantities", "rack_count:house:rack")] == (True, 1, 2, 1)
    assert current.dirty and current.revision == 2


def test_long_pool_profile_round_trip():
    config = Configuration()
    config.set("pools", 1)
    config.pool_values = tuple(1.123456789012345 for _ in range(8760))
    config.pool_source = "user input"
    text = export_scenario(config)
    assert len(text) > 131072
    assert import_scenario(text).pool_values == config.pool_values


def test_default_reference_missing_and_complete_demo_available():
    reference = load_default("reference")
    complete = load_default("complete")
    ref = run_simulation(reference).evaluation.metrics
    demo = run_simulation(complete)
    assert ref.economics.annualized_total_cost_chf.value is None
    assert ref.economics.compute_income_chf.value is None
    assert demo.evaluation.metrics.economics.annualized_total_cost_chf.value == pytest.approx(
        8486.92611028096
    )
    assert demo.evaluation.metrics.economics.compute_income_chf.value == 1200
    assert demo.installed_capacity_tflop_per_s == 2
    assert demo.evaluation.metrics.compute_utilization is None
    assert "synthetic" in complete.metadata["hardware_costs:per_rack"].provenance.source
    assert "ElCom" in complete.metadata["electricity_price:house"].provenance.source
    complete.set("electricity_price:house", 0.4)
    assert complete.metadata["electricity_price:house"].provenance.source == "user input"
    assert (
        "user input"
        in import_scenario(export_scenario(complete))
        .metadata["electricity_price:house"]
        .provenance.source
    )


def test_template_is_importable_complete_and_inventory_covers_every_parameter():
    from digitalheat_simulator.application.dashboard import reference_fields

    text = (DEFAULTS / "scenario-template.csv").read_text(encoding="utf-8")
    config = import_scenario(text)
    entries = rows(text)
    parameter_ids = {row["identifier"] for row in entries if row["kind"] == "parameter"}
    expected = {field.identifier for field in reference_fields()} | set(_synthetic_fields())
    assert parameter_ids == expected and len(parameter_ids) == 46
    assert config.mode == "reference" and config.values["capacity"] is None
    assert config.ranges[("quantities", "rack_count:house:rack")] == (False, None, None, None)
    inventory = Path("docs/SCENARIO_PARAMETERS.md").read_text(encoding="utf-8")
    assert all(f"`{identifier}`" in inventory for identifier in expected)
    for setting in ("mode", "objective", "budget", "pool_profile", "pool_source"):
        assert f"`{setting}`" in inventory


def test_template_edited_values_export_and_import_again():
    text = (DEFAULTS / "scenario-template.csv").read_text(encoding="utf-8")
    text = changed(text, "racks", value="2", source="user input")
    text = changed(text, "storage", value="40", source="user input")
    config = import_scenario(text)
    config.set("storage", 45)
    restored = import_scenario(export_scenario(config))
    assert restored.values["racks"] == 2
    assert restored.values["storage"] == 45
    assert restored.ranges == config.ranges
    assert restored.metadata["storage"].provenance.source == "user input"
