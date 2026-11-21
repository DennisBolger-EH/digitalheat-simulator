"""Versioned scenario CSV for the existing Dashboard configuration."""

import csv
import io
from dataclasses import replace
from datetime import date
from decimal import Decimal, InvalidOperation
from math import isfinite
from pathlib import Path

from digitalheat_simulator.application.dashboard import (
    Configuration,
    _source,
    prepare,
    reference_fields,
    validate,
)
from digitalheat_simulator.application.optimization_demo import example
from digitalheat_simulator.domain.parameters import Parameter, Provenance

VERSION = "1"
csv.field_size_limit(2_000_000)
COLUMNS = (
    "version",
    "kind",
    "group",
    "identifier",
    "label",
    "value",
    "data_type",
    "unit",
    "enabled",
    "optimizable",
    "minimum",
    "maximum",
    "step",
    "uncertainty_min",
    "uncertainty_max",
    "source",
    "source_unit",
    "publication_date",
    "access_date",
    "applicability",
    "transformation",
    "description",
    "default",
)
DEFAULTS = Path(__file__).parent / "defaults"


def load_default(name: str) -> Configuration:
    if name not in ("reference", "complete"):
        raise ValueError("Unknown default scenario")
    return import_scenario((DEFAULTS / f"{name}.csv").read_text(encoding="utf-8"))


def _synthetic_fields():
    return {
        f"synthetic:{group.identifier}:{parameter.identifier}": (group.identifier, parameter)
        for group in example()[2]
        for parameter in group.parameters
    }


def _range_keys():
    result = {}
    fields = {item.identifier: item for item in reference_fields()}
    for site, count, racks, storage in (
        ("house", "houses", "racks", "storage"),
        ("pool", "pools", "pool_racks", "pool_storage"),
    ):
        for group, identifier, source in (
            ("quantities", f"site_count:{site}", count),
            ("quantities", f"rack_count:{site}:rack", racks),
            ("storage", f"capacity_kwh:{site}", storage),
            ("rack_technical", f"electrical_power_kw:{site}:rack", "electrical"),
            ("rack_technical", f"thermal_power_kw:{site}:rack", "thermal"),
            ("rack_technical", f"recovery_efficiency:{site}:rack", "efficiency"),
            *(
                ("energy_costs", f"{name}:{site}", f"{name}:{site}")
                for name in ("electricity_price", "heat_value", "backup_price")
            ),
        ):
            result[group, identifier] = fields[source]
    for item in fields.values():
        if item.group in ("Hardware costs", "Installation costs", "Service / OPEX"):
            name, basis = item.identifier.split(":")
            group = "running_service_costs" if name == "other_opex" else name
            prefix = (
                "other_"
                if name == "other_opex"
                else "service_"
                if name == "running_service_costs"
                else ""
            )
            result[group, prefix + basis] = item
        elif item.group in ("Finance", "Compute income"):
            group = "finance_parameters" if item.group == "Finance" else "compute_income"
            result[group, item.identifier] = item
    return result


def _text(value):
    if value is None:
        return ""
    if type(value) is bool:
        return str(value).lower()
    return str(value)


def _parameter_row(group, key, value, parameter):
    row = {
        "version": VERSION,
        "kind": "parameter",
        "group": group,
        "identifier": key,
        "value": _text(value),
        "label": parameter.label or "",
        "data_type": parameter.data_type,
        "unit": parameter.unit or "",
        "enabled": _text(parameter.enabled),
        "optimizable": _text(parameter.optimizable),
        "minimum": _text(parameter.minimum),
        "maximum": _text(parameter.maximum),
        "step": _text(parameter.step),
        "description": parameter.description or "",
        "default": _text(parameter.default),
    }
    if parameter.uncertainty_range:
        row["uncertainty_min"], row["uncertainty_max"] = map(_text, parameter.uncertainty_range)
    if parameter.provenance:
        p = parameter.provenance
        row.update(
            source=p.source,
            source_unit=p.unit or "",
            publication_date=_text(p.publication_date),
            access_date=_text(p.access_date),
            applicability=p.applicability or "",
            transformation=p.transformation or "",
        )
    return row


def export_scenario(config: Configuration) -> str:
    if config.pool_text:
        profile = tuple(
            _number(line.strip(), "pool profile")
            for line in config.pool_text.splitlines()
            if line.strip()
        )
        if profile != config.pool_values:
            raise ValueError("Pool profile text does not match the configured hourly values")
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for item in reference_fields():
        value = config.values.get(item.identifier)
        metadata = config.metadata.get(item.identifier)
        if metadata is None:
            metadata = Parameter(
                item.identifier,
                0 if item.integer else 0.0,
                "integer" if item.integer else "number",
                "scenario",
                item.unit,
                label=item.label,
                provenance=_source(config, item) if value is not None else None,
            )
        writer.writerow(_parameter_row(item.group, item.identifier, value, metadata))
    for key, (group, parameter) in _synthetic_fields().items():
        value = config.values.get(key, parameter.value)
        metadata = config.metadata.get(key, parameter)
        if key in config.edited and key not in config.metadata:
            metadata = replace(
                metadata,
                provenance=Provenance("user input in synthetic demonstration", unit=parameter.unit),
            )
        writer.writerow(_parameter_row("synthetic/" + group, key, value, metadata))
    for key, (enabled, lower, upper, step) in sorted(config.ranges.items()):
        group, identifier = key
        item = _range_keys().get(key)
        if item is None:
            raise ValueError(f"Unknown optimization parameter {group}/{identifier}")
        writer.writerow(
            {
                "version": VERSION,
                "kind": "range",
                "group": group,
                "identifier": identifier,
                "data_type": "integer" if item.integer else "number",
                "unit": item.unit,
                "enabled": "true",
                "optimizable": _text(enabled),
                "minimum": _text(lower),
                "maximum": _text(upper),
                "step": _text(step),
            }
        )
    for key, value, data_type in (
        ("mode", config.mode, "string"),
        ("objective", config.objective, "string"),
        ("budget", config.budget, "integer"),
        ("pool_source", config.pool_source, "string"),
        (
            "pool_profile",
            config.pool_text
            or ("\n".join(map(str, config.pool_values)) if config.pool_values is not None else ""),
            "string",
        ),
    ):
        writer.writerow(
            {
                "version": VERSION,
                "kind": "setting",
                "group": "scenario",
                "identifier": key,
                "value": _text(value),
                "data_type": data_type,
            }
        )
    return output.getvalue()


def _bool(value, name):
    if value == "":
        return None
    if value not in ("true", "false"):
        raise ValueError(f"{name} must be true or false")
    return value == "true"


def _number(value, name, integer=False, optional=False):
    if value == "" and optional:
        return None
    if integer:
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"{name} must be a valid number") from exc
        if not number.is_finite():
            raise ValueError(f"{name} must be finite")
        if number != number.to_integral_value():
            raise ValueError(f"{name} must be a whole number")
        if abs(number) > 9_007_199_254_740_991:
            raise ValueError(f"{name} exceeds the safe integer range for the interface")
        return int(number)
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid number") from exc
    if not isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _date(value, name):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date") from exc


def import_scenario(text: str) -> Configuration:
    """Validate all rows into a new configuration before returning it."""
    if len(text) > 2_000_000:
        raise ValueError("Scenario CSV exceeds the 2 MB limit")
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    try:
        if reader.fieldnames != list(COLUMNS):
            raise ValueError("Scenario CSV columns do not match schema version 1")
    except csv.Error as exc:
        raise ValueError("Malformed CSV header") from exc
    fields = {item.identifier: item for item in reference_fields()}
    synthetic = _synthetic_fields()
    allowed_ranges = _range_keys()
    seen = set()
    values, metadata, ranges, settings = {}, {}, {}, {}
    try:
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Line {reader.line_num}: malformed row")
            if row["version"] != VERSION:
                raise ValueError(f"Line {reader.line_num}: unsupported scenario CSV version")
            kind, group, key = row["kind"], row["group"], row["identifier"]
            identity = (kind, group, key)
            if identity in seen:
                raise ValueError(f"Duplicate parameter {group}/{key}")
            seen.add(identity)
            if kind == "parameter":
                if key in fields and group == fields[key].group:
                    item = fields[key]
                    dtype, unit = ("integer" if item.integer else "number"), item.unit
                elif key in synthetic and group == "synthetic/" + synthetic[key][0]:
                    item = synthetic[key][1]
                    dtype, unit = item.data_type, item.unit
                else:
                    raise ValueError(f"Unknown parameter {group}/{key}")
                if row["data_type"] != dtype or row["unit"] != unit:
                    raise ValueError(f"{key}: data type or unit does not match ({dtype}, {unit})")
                value = _number(row["value"], key, dtype == "integer", optional=True)
                enabled = _bool(row["enabled"], f"{key} enabled")
                optimizable = _bool(row["optimizable"], f"{key} optimizable")
                if enabled is False and (
                    key in synthetic
                    or key
                    in {
                        "houses",
                        "pools",
                        "racks",
                        "pool_racks",
                        "storage",
                        "initial",
                        "pool_storage",
                        "pool_initial",
                        "electrical",
                        "thermal",
                        "efficiency",
                    }
                ):
                    raise ValueError(f"{key}: required physical inputs cannot be disabled")
                minimum = _number(row["minimum"], f"{key} minimum", dtype == "integer", True)
                maximum = _number(row["maximum"], f"{key} maximum", dtype == "integer", True)
                step = _number(row["step"], f"{key} step", dtype == "integer", True)
                if optimizable and any(x is None for x in (minimum, maximum, step)):
                    raise ValueError(
                        f"{key}: optimizable parameters require minimum, maximum and step"
                    )
                umin = _number(row["uncertainty_min"], f"{key} uncertainty minimum", optional=True)
                umax = _number(row["uncertainty_max"], f"{key} uncertainty maximum", optional=True)
                if (umin is None) != (umax is None):
                    raise ValueError(f"{key}: both uncertainty bounds are required")
                provenance = None
                if row["source"]:
                    provenance = Provenance(
                        row["source"],
                        _date(row["publication_date"], key),
                        _date(row["access_date"], key),
                        row["source_unit"] or None,
                        row["applicability"] or None,
                        row["transformation"] or None,
                    )
                elif any(
                    row[name]
                    for name in (
                        "source_unit",
                        "publication_date",
                        "access_date",
                        "applicability",
                        "transformation",
                    )
                ):
                    raise ValueError(f"{key}: provenance source is required")
                default = _number(
                    row["default"], f"{key} default", dtype == "integer", optional=True
                )
                if value is None:
                    if (
                        any(x is not None for x in (minimum, maximum, step, umin, umax, default))
                        or provenance
                        or enabled is not None
                        or optimizable is not None
                        or row["description"]
                    ):
                        raise ValueError(f"{key}: metadata requires a value")
                    if row["label"] != (item.label or key):
                        raise ValueError(f"{key}: custom label requires a value")
                else:
                    if value < 0:
                        raise ValueError(f"{key} must be >= 0 {unit}")
                    if provenance is None:
                        raise ValueError(f"{key}: source is required for supplied values")
                    if (
                        key in fields
                        and fields[key].provenance is not None
                        and provenance == fields[key].provenance
                        and value != fields[key].value
                    ):
                        raise ValueError(
                            f"{key}: modified value cannot retain the reference provenance; "
                            "provide its actual source"
                        )
                    metadata[key] = Parameter(
                        key,
                        value,
                        dtype,
                        "scenario",
                        unit,
                        row["label"] or None,
                        row["description"] or None,
                        minimum,
                        maximum,
                        step,
                        default,
                        (umin, umax) if umin is not None else None,
                        optimizable,
                        enabled,
                        provenance,
                    )
                values[key] = value
            elif kind == "range":
                item = allowed_ranges.get((group, key))
                if item is None:
                    raise ValueError(f"Unknown optimization parameter {group}/{key}")
                if (
                    row["data_type"] != ("integer" if item.integer else "number")
                    or row["unit"] != item.unit
                ):
                    raise ValueError(f"{key}: invalid range type or unit")
                if _bool(row["enabled"], f"{key} enabled") is not True:
                    raise ValueError(f"{key}: range enabled must be true")
                active = _bool(row["optimizable"], f"{key} optimizable")
                if active is None:
                    raise ValueError(f"{key}: optimizable flag is required")
                lo, hi, step = (
                    _number(row[name], f"{key} {name}", item.integer, optional=True)
                    for name in ("minimum", "maximum", "step")
                )
                if active and any(x is None for x in (lo, hi, step)):
                    raise ValueError(f"{key}: minimum, maximum and step are required")
                if (lo is not None and hi is not None and lo > hi) or (
                    step is not None and step <= 0
                ):
                    raise ValueError(f"{key}: invalid minimum, maximum or step")
                if any(
                    row[name]
                    for name in COLUMNS
                    if name
                    not in {
                        "version",
                        "kind",
                        "group",
                        "identifier",
                        "data_type",
                        "unit",
                        "enabled",
                        "optimizable",
                        "minimum",
                        "maximum",
                        "step",
                    }
                ):
                    raise ValueError(f"{key}: unsupported range metadata")
                ranges[group, key] = (active, lo, hi, step)
            elif (
                kind == "setting"
                and group == "scenario"
                and key in {"mode", "objective", "budget", "pool_source", "pool_profile"}
            ):
                if row["data_type"] != ("integer" if key == "budget" else "string"):
                    raise ValueError(f"{key}: invalid setting type")
                if any(
                    row[name]
                    for name in COLUMNS
                    if name not in {"version", "kind", "group", "identifier", "data_type", "value"}
                ):
                    raise ValueError(f"{key}: unsupported setting metadata")
                settings[key] = (
                    _number(row["value"], key, True) if key == "budget" else row["value"]
                )
            else:
                raise ValueError(f"Unknown scenario row {kind}/{group}/{key}")
    except csv.Error as exc:
        raise ValueError(f"Malformed CSV near line {reader.line_num}") from exc
    required = set(fields) | set(synthetic)
    if set(values) != required or set(settings) != {
        "mode",
        "objective",
        "budget",
        "pool_source",
        "pool_profile",
    }:
        raise ValueError("Scenario CSV is incomplete: required parameters or settings are missing")
    if settings["mode"] not in ("reference", "synthetic") or settings["objective"] not in (
        "economic",
        "thermal",
    ):
        raise ValueError("Unknown scenario mode or optimization objective")
    pool_text = settings["pool_profile"]
    pool_values = (
        tuple(_number(x.strip(), "pool profile") for x in pool_text.splitlines() if x.strip())
        if pool_text
        else None
    )
    if pool_values is not None and (len(pool_values) != 8760 or any(x < 0 for x in pool_values)):
        raise ValueError("Pool profile must contain 8,760 nonnegative hourly kWh values")
    config = Configuration(
        mode=settings["mode"],
        values=values,
        metadata=metadata,
        pool_values=pool_values,
        pool_text=pool_text,
        pool_source=settings["pool_source"],
        objective=settings["objective"],
        budget=settings["budget"],
        ranges=ranges,
    )
    validate(config)
    _, _, groups, _ = prepare(config)
    applicable = {
        (group.identifier, parameter.identifier)
        for group in groups
        for parameter in group.parameters
    }
    for key, (active, _, _, _) in config.ranges.items():
        if active and key not in applicable:
            raise ValueError(f"{key[0]}/{key[1]}: active range is not applicable to this scenario")
    return config
