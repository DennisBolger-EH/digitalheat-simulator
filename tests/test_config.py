import json
from datetime import date

import pytest

from digitalheat_simulator.config.json_loader import JsonParameterConfigurationLoader
from digitalheat_simulator.domain.parameters import ParameterGroup


def test_json_loader_preserves_optional_metadata_and_supports_custom_groups(tmp_path):
    path = tmp_path / "parameters.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "groups": [
                    {
                        "identifier": "new-group",
                        "parameters": [
                            {
                                "identifier": "power",
                                "value": 1,
                                "data_type": "number",
                                "scope": "unit",
                                "unit": "kW",
                                "uncertainty_range": [0.8, 1.2],
                                "provenance": {
                                    "source": "example",
                                    "access_date": "2026-01-02",
                                    "unit": "kW",
                                    "applicability": "example",
                                    "transformation": "none",
                                },
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = JsonParameterConfigurationLoader().load(path)
    assert isinstance(result[0], ParameterGroup)
    parameter = result[0].parameters[0]
    assert parameter.uncertainty_range == (0.8, 1.2)
    assert parameter.provenance.access_date == date(2026, 1, 2)
    assert JsonParameterConfigurationLoader().load(path) == result


@pytest.mark.parametrize(
    "document",
    [
        {"version": 2, "groups": []},
        {"version": True, "groups": []},
        {"version": 1, "groups": {}, "extra": 1},
        {"version": 1, "groups": [{"identifier": "x", "parameters": []}] * 2},
        {"version": 1, "groups": [{"identifier": "x", "parameters": [{"identifier": "x"}]}]},
    ],
)
def test_invalid_configuration_fails_explicitly(tmp_path, document):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises((ValueError, TypeError)):
        JsonParameterConfigurationLoader().load(path)
