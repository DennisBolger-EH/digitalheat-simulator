from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pint.errors import DimensionalityError

from digitalheat_simulator.domain.time import TimeGrid
from digitalheat_simulator.domain.units import convert


def test_unit_conversion_and_dimensions():
    assert convert(1, "MWh", "kWh") == pytest.approx(1000)
    assert convert(0, "degC", "kelvin") == pytest.approx(273.15)
    assert convert(1, "CHF / MWh", "CHF / kWh") == pytest.approx(0.001)
    assert convert(1, "TFLOPS", "FLOPS") == pytest.approx(1e12)
    with pytest.raises(DimensionalityError):
        convert(1, "kW", "kWh")
    with pytest.raises(ValueError):
        convert(1, "", "kW")


@pytest.mark.parametrize(("year", "hours"), [(2025, 8760), (2024, 8784)])
def test_local_year_has_correct_elapsed_hours(year, hours):
    zone = ZoneInfo("Europe/Zurich")
    grid = TimeGrid(datetime(year, 1, 1, tzinfo=zone), datetime(year + 1, 1, 1, tzinfo=zone))
    assert len(grid.instants()) == hours
    assert grid.instants() == grid.instants()


@pytest.mark.parametrize(("month", "day", "hours"), [(3, 30, 23), (10, 26, 25)])
def test_local_dst_day_uses_elapsed_time(month, day, hours):
    zone = ZoneInfo("Europe/Zurich")
    grid = TimeGrid(
        datetime(2025, month, day, tzinfo=zone),
        datetime(2025, month, day + 1, tzinfo=zone),
    )
    instants = grid.instants()
    assert len(instants) == hours
    assert len({instant.astimezone(UTC) for instant in instants}) == hours


def test_resolution_and_invalid_boundaries():
    start = datetime(2025, 1, 1, tzinfo=UTC)
    assert len(TimeGrid(start, start + timedelta(hours=1), timedelta(minutes=15)).instants()) == 4
    with pytest.raises(ValueError):
        TimeGrid(datetime(2025, 1, 1), datetime(2025, 1, 2))
    with pytest.raises(ValueError):
        TimeGrid(start, start + timedelta(hours=1), timedelta(minutes=40))
    with pytest.raises(ValueError):
        TimeGrid(start, start + timedelta(hours=1), timedelta(0))
