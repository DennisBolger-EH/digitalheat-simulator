from datetime import UTC, datetime, timedelta

import pytest

from digitalheat_simulator.data.pool_demand import pool_demand
from digitalheat_simulator.domain.parameters import Provenance
from digitalheat_simulator.domain.scenario import DemandPoint, Interval, ThermalDemandSeries
from digitalheat_simulator.domain.thermal import energy_kwh


def test_pool_profile_and_provenance():
    start = datetime(2025, 1, 1, tzinfo=UTC)
    point = DemandPoint(Interval(start, start + timedelta(hours=1)), energy_kwh(1000, "Wh"))
    source = Provenance("user-provided synthetic test", unit="kWh", transformation="Wh to kWh")
    profile = pool_demand("pool", (point,), source)
    assert profile.points[0].energy_kwh == 1
    assert profile.provenance == source


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True])
def test_invalid_pool_energy_rejected(value):
    start = datetime(2025, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError):
        DemandPoint(Interval(start, start + timedelta(hours=1)), value)


def test_invalid_pool_series_rejected():
    start = datetime(2025, 1, 1, tzinfo=UTC)
    point = DemandPoint(Interval(start, start + timedelta(hours=1)), 1)
    gap = DemandPoint(Interval(start + timedelta(hours=2), start + timedelta(hours=3)), 1)
    with pytest.raises(ValueError, match="contiguous"):
        ThermalDemandSeries("pool", (point, gap), Provenance("input", unit="kWh"))
    with pytest.raises(ValueError, match="contiguous"):
        ThermalDemandSeries("pool", (point, point), Provenance("input", unit="kWh"))
    with pytest.raises(ValueError, match="unit"):
        ThermalDemandSeries("pool", (point,), Provenance("input", unit="kW"))
    with pytest.raises(TypeError, match="provenance"):
        ThermalDemandSeries("pool", (point,), None)
