"""Application-owned collection of independently editable scenarios."""

from dataclasses import dataclass
from datetime import datetime

from digitalheat_simulator.application.dashboard import Configuration


@dataclass
class BundleScenario:
    scenario_id: str
    scenario_name: str
    configuration: Configuration
    saved_revision: int = 0

    @property
    def dirty(self) -> bool:
        return self.configuration.revision != self.saved_revision


@dataclass
class ScenarioBundle:
    format_version: int
    source_filename: str
    imported_at: datetime | None
    scenarios: dict[str, BundleScenario]
    active_scenario_id: str

    @property
    def active(self) -> BundleScenario:
        return self.scenarios[self.active_scenario_id]

    @property
    def dirty(self) -> bool:
        return any(scenario.dirty for scenario in self.scenarios.values())

    def select(self, scenario_id: str) -> BundleScenario:
        if scenario_id not in self.scenarios:
            raise ValueError(f"Unknown scenario ID: {scenario_id}")
        self.active_scenario_id = scenario_id
        return self.active

    def mark_saved(self) -> None:
        for scenario in self.scenarios.values():
            scenario.saved_revision = scenario.configuration.revision
