"""Versioned JSON parameter configuration adapter."""

import json
from datetime import date
from pathlib import Path

from digitalheat_simulator.domain.parameters import Parameter, ParameterGroup, Provenance


class JsonParameterConfigurationLoader:
    def load(self, path: Path) -> tuple[ParameterGroup, ...]:
        with path.open(encoding="utf-8") as file:
            document = json.load(file)
        if not isinstance(document, dict) or set(document) != {"version", "groups"}:
            raise ValueError("Configuration must contain only version and groups")
        if type(document["version"]) is not int or document["version"] != 1:
            raise ValueError("Unsupported configuration version")
        if not isinstance(document["groups"], list):
            raise TypeError("groups must be a list")
        groups = []
        for raw_group in document["groups"]:
            if not isinstance(raw_group, dict) or not isinstance(raw_group.get("parameters"), list):
                raise TypeError("Each group must contain a parameters list")
            group = dict(raw_group)
            raw_parameters = group.pop("parameters")
            parameters = []
            for raw_parameter in raw_parameters:
                if not isinstance(raw_parameter, dict):
                    raise TypeError("Each parameter must be an object")
                parameter = dict(raw_parameter)
                if parameter.get("provenance") is not None:
                    source = parameter["provenance"]
                    if not isinstance(source, dict):
                        raise ValueError("provenance must be an object")
                    source = dict(source)
                    for field in ("publication_date", "access_date"):
                        if field in source and source[field] is not None:
                            source[field] = date.fromisoformat(source[field])
                    parameter["provenance"] = Provenance(**source)
                if parameter.get("uncertainty_range") is not None:
                    bounds = parameter["uncertainty_range"]
                    if not isinstance(bounds, list):
                        raise ValueError("uncertainty_range must be a list")
                    parameter["uncertainty_range"] = tuple(bounds)
                parameters.append(Parameter(**parameter))
            groups.append(ParameterGroup(parameters=tuple(parameters), **group))
        if len({group.identifier for group in groups}) != len(groups):
            raise ValueError("Group identifiers must be unique")
        return tuple(groups)
