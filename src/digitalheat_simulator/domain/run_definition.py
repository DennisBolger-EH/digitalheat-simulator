"""Inputs needed to identify a future reproducible simulation."""

from dataclasses import dataclass

from digitalheat_simulator.domain.parameters import ParameterGroup


@dataclass(frozen=True)
class DatasetVersion:
    identifier: str
    version: str

    def __post_init__(self) -> None:
        if not all(
            isinstance(item, str) and item.strip() for item in (self.identifier, self.version)
        ):
            raise ValueError("Dataset identifier and version must be non-empty strings")


@dataclass(frozen=True)
class RunDefinition:
    scenario: str
    parameters: tuple[ParameterGroup, ...]
    datasets: tuple[DatasetVersion, ...]
    model_version: str
    random_seed: int | None = None

    def __post_init__(self) -> None:
        if not all(
            isinstance(item, str) and item.strip() for item in (self.scenario, self.model_version)
        ):
            raise ValueError("Scenario and model version must be non-empty strings")
        if not isinstance(self.parameters, tuple) or not all(
            isinstance(item, ParameterGroup) for item in self.parameters
        ):
            raise ValueError("parameters must be a tuple of ParameterGroup instances")
        if not isinstance(self.datasets, tuple) or not all(
            isinstance(item, DatasetVersion) for item in self.datasets
        ):
            raise ValueError("datasets must be a tuple of DatasetVersion instances")
        if len({item.identifier for item in self.parameters}) != len(self.parameters):
            raise ValueError("Group identifiers must be unique")
        if len({item.identifier for item in self.datasets}) != len(self.datasets):
            raise ValueError("Dataset identifiers must be unique")
        if self.random_seed is not None and type(self.random_seed) is not int:
            raise ValueError("random_seed must be an integer or None")
