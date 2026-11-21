"""Construct a supplied per-pool demand series without physical assumptions."""

from digitalheat_simulator.domain.parameters import Provenance
from digitalheat_simulator.domain.scenario import DemandPoint, ThermalDemandSeries


def pool_demand(
    identifier: str, points: tuple[DemandPoint, ...], provenance: Provenance
) -> ThermalDemandSeries:
    return ThermalDemandSeries(identifier, points, provenance)
