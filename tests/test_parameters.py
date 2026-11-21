from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from digitalheat_simulator.domain.parameters import Parameter, ParameterGroup, Provenance
from digitalheat_simulator.domain.run_definition import DatasetVersion, RunDefinition


def test_parameter_metadata_and_provenance_are_immutable():
    provenance = Provenance(
        source="example",
        publication_date=date(2025, 1, 1),
        access_date=date(2026, 1, 1),
        unit="kW",
        applicability="example scenario",
        transformation="none",
    )
    parameter = Parameter(
        identifier="power",
        value=1.5,
        data_type="number",
        scope="unit",
        unit="kW",
        minimum=0,
        maximum=3,
        step=0.1,
        default=1,
        uncertainty_range=(1, 2),
        optimizable=True,
        provenance=provenance,
    )
    assert parameter.provenance == provenance
    with pytest.raises(FrozenInstanceError):
        parameter.value = 2


@pytest.mark.parametrize(
    "changes",
    [
        {"value": True},
        {"value": float("nan")},
        {"value": 11},
        {"default": -1},
        {"minimum": 11},
        {"step": 0},
        {"unit": ""},
        {"scope": "unknown"},
        {"uncertainty_range": (2, 1)},
        {"enabled": "yes"},
    ],
)
def test_invalid_parameters_are_rejected(changes):
    kwargs = {
        "identifier": "capacity",
        "value": 5,
        "data_type": "number",
        "scope": "scenario",
        "unit": "kW",
        "minimum": 0,
        "maximum": 10,
    }
    kwargs.update(changes)
    with pytest.raises(ValueError):
        Parameter(**kwargs)


def test_group_and_run_definition_reject_duplicates():
    parameter = Parameter("x", True, "boolean", "unit")
    group = ParameterGroup("custom", (parameter,))
    with pytest.raises(ValueError):
        ParameterGroup("custom", (parameter, parameter))
    with pytest.raises(ValueError):
        RunDefinition("scenario", (group, group), (), "v1")
    with pytest.raises(ValueError):
        RunDefinition(
            "scenario", (), (DatasetVersion("data", "v1"), DatasetVersion("data", "v2")), "v1"
        )


def test_run_definition_captures_reproducibility_inputs():
    group = ParameterGroup("custom", (Parameter("ratio", 0.5, "number", "unit", "dimensionless"),))
    run = RunDefinition("scenario", (group,), (DatasetVersion("weather", "2025"),), "v1", 42)
    assert run == RunDefinition(
        "scenario", (group,), (DatasetVersion("weather", "2025"),), "v1", 42
    )
    assert run.random_seed == 42
    with pytest.raises(FrozenInstanceError):
        run.random_seed = 1
