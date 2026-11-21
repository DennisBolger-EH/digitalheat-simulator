"""Format-independent configuration loading boundary."""

from pathlib import Path
from typing import Protocol

from digitalheat_simulator.domain.parameters import ParameterGroup


class ParameterConfigurationLoader(Protocol):
    def load(self, path: Path) -> tuple[ParameterGroup, ...]:
        """Load and validate groups from a configuration source."""
        ...
