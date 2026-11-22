"""Versioned multi-scenario CSV, using the existing single-scenario validator."""

import csv
import io
import re
from datetime import UTC, datetime
from pathlib import PurePath

from digitalheat_simulator.application.scenario_bundle import BundleScenario, ScenarioBundle
from digitalheat_simulator.config.scenario_csv import COLUMNS, export_scenario, import_scenario

BUNDLE_COLUMNS = ("version", "scenario_id", "scenario_name", *COLUMNS[1:])
MAX_BYTES = 2_000_000
SAFE_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def _legacy_identity(filename: str) -> tuple[str, str]:
    name = PurePath(filename.replace("\\", "/")).stem.strip() or "Imported scenario"
    identifier = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "imported-scenario"
    return identifier, name


def import_bundle(text: str, filename: str) -> ScenarioBundle:
    """Return a fully validated bundle; never mutate an existing bundle."""
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Scenario CSV exceeds the 2 MB limit")
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    try:
        header = reader.fieldnames
        if header == list(COLUMNS):
            identifier, name = _legacy_identity(filename)
            scenario = BundleScenario(identifier, name, import_scenario(text))
            return ScenarioBundle(
                1, filename, datetime.now(UTC), {identifier: scenario}, identifier
            )
        if header != list(BUNDLE_COLUMNS):
            raise ValueError("Scenario CSV columns do not match version 1 or 2")
        groups: dict[str, tuple[str, list[dict[str, str]]]] = {}
        names: dict[str, str] = {}
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Line {reader.line_num}: malformed row")
            if row["version"] != "2":
                raise ValueError(f"Line {reader.line_num}: unsupported scenario CSV version")
            identifier, name = row["scenario_id"], row["scenario_name"]
            if not SAFE_ID.fullmatch(identifier):
                raise ValueError(
                    f"Scenario ID {identifier!r} must use lowercase letters, digits and hyphens"
                )
            if not name.strip() or name != name.strip():
                raise ValueError(
                    f"Scenario ID {identifier!r} requires a name without outer whitespace"
                )
            if identifier in groups and groups[identifier][0] != name:
                raise ValueError(
                    f'Scenario ID "{identifier}" is defined with two different names: '
                    f'"{groups[identifier][0]}" and "{name}"'
                )
            if name.casefold() in names and names[name.casefold()] != identifier:
                raise ValueError(f'Duplicate scenario name "{name}"')
            names[name.casefold()] = identifier
            if identifier not in groups:
                groups[identifier] = (name, [])
            groups[identifier][1].append({**{key: row[key] for key in COLUMNS}, "version": "1"})
        if not groups:
            raise ValueError("Scenario bundle contains no scenarios")
        scenarios = {}
        for identifier, (name, rows) in groups.items():
            output = io.StringIO(newline="")
            writer = csv.DictWriter(output, fieldnames=COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            try:
                config = import_scenario(output.getvalue())
            except ValueError as exc:
                raise ValueError(f'Scenario "{name}" ({identifier}): {exc}') from exc
            scenarios[identifier] = BundleScenario(identifier, name, config)
        return ScenarioBundle(2, filename, datetime.now(UTC), scenarios, next(iter(scenarios)))
    except csv.Error as exc:
        raise ValueError(f"Malformed CSV near line {reader.line_num}") from exc


def export_bundle(bundle: ScenarioBundle) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=BUNDLE_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for scenario in bundle.scenarios.values():
        reader = csv.DictReader(io.StringIO(export_scenario(scenario.configuration), newline=""))
        for row in reader:
            writer.writerow(
                {
                    **row,
                    "version": "2",
                    "scenario_id": scenario.scenario_id,
                    "scenario_name": scenario.scenario_name,
                }
            )
    text = output.getvalue()
    import_bundle(text, "digitalheat-scenarios.csv")
    return text
