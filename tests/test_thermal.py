from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pint.errors import DimensionalityError

from digitalheat_simulator.domain.thermal import (
    Rack,
    ThermalInterval,
    energy_kwh,
    power_kw,
)
from digitalheat_simulator.simulation.thermal import balance_interval, simulate

START = datetime(2025, 1, 1, tzinfo=UTC)
RACK = Rack(1, 1, 0.8)


def interval(demand=0, on=True, start=START, duration=1):
    return ThermalInterval(start, start + timedelta(hours=duration), demand, 0, on)


@pytest.mark.parametrize(
    ("demand", "on", "opening", "capacity", "direct", "charge", "discharge", "dump", "backup"),
    [
        (0, True, 0, 35, 0, 0.8, 0, 0, 0),
        (1, False, 0, 35, 0, 0, 0, 0, 1),
        (0.8, True, 0, 35, 0.8, 0, 0, 0, 0),
        (2, True, 0, 35, 0.8, 0, 0, 0, 1.2),
        (0.3, True, 35, 35, 0.3, 0, 0, 0.5, 0),
        (2, False, 1.5, 35, 0, 0, 1.5, 0, 0.5),
        (0, True, 34.5, 35, 0, 0.5, 0, 0.3, 0),
        (0, True, 0, 0, 0, 0, 0, 0.8, 0),
    ],
)
def test_known_balances(demand, on, opening, capacity, direct, charge, discharge, dump, backup):
    result = balance_interval(interval(demand, on), RACK, capacity, opening)
    assert result.direct_supply_kwh == pytest.approx(direct)
    assert result.storage_charge_kwh == pytest.approx(charge)
    assert result.storage_discharge_kwh == pytest.approx(discharge)
    assert result.dumped_heat_kwh == pytest.approx(dump)
    assert result.backup_heat_kwh == pytest.approx(backup)
    assert result.storage_closing_kwh == pytest.approx(opening + charge - discharge)
    result.validate_balances()


def test_storage_charged_in_one_interval_is_available_only_in_next():
    run = simulate((interval(), interval(1, False, start=START + timedelta(hours=1))), RACK, 35, 0)
    assert run.results[0].storage_discharge_kwh == 0
    assert run.results[0].storage_closing_kwh == pytest.approx(0.8)
    assert run.results[1].storage_opening_kwh == pytest.approx(0.8)
    assert run.results[1].storage_discharge_kwh == pytest.approx(0.8)
    assert run.results[1].backup_heat_kwh == pytest.approx(0.2)


def test_power_energy_units_and_half_hour():
    assert power_kw(1000, "W") == pytest.approx(1)
    assert energy_kwh(1, "MWh") == pytest.approx(1000)
    with pytest.raises(DimensionalityError):
        power_kw(1, "kWh")
    with pytest.raises(DimensionalityError):
        energy_kwh(1, "kW")
    result = balance_interval(interval(duration=0.5), RACK, 35, 0)
    assert result.electrical_energy_kwh == pytest.approx(0.5)
    assert result.gross_heat_kwh == pytest.approx(0.5)
    assert result.recoverable_heat_kwh == pytest.approx(0.4)
    assert result.unrecovered_heat_kwh == pytest.approx(0.1)


@pytest.mark.parametrize("field", ["backup_heat_kwh", "dumped_heat_kwh", "storage_closing_kwh"])
def test_invariant_checker_rejects_each_independently(field):
    result = balance_interval(interval(1), RACK, 35, 0)
    with pytest.raises(ValueError, match="balance violated"):
        replace(result, **{field: getattr(result, field) + 0.01}).validate_balances()


def test_sequence_is_deterministic_and_rejects_gaps_and_empty_input():
    inputs = (interval(), interval(1, False, START + timedelta(hours=1)))
    assert simulate(inputs, RACK, 35, 0) == simulate(inputs, RACK, 35, 0)
    with pytest.raises(ValueError, match="contiguous"):
        simulate((inputs[0], interval(start=START + timedelta(hours=2))), RACK, 35, 0)
    with pytest.raises(ValueError, match="at least one"):
        simulate((), RACK, 35, 0)


@pytest.mark.parametrize(
    "action",
    [
        lambda: Rack(-1, 1, 0.8),
        lambda: Rack(1, float("nan"), 0.8),
        lambda: Rack(1, 1, 1.1),
        lambda: interval(-1),
        lambda: interval(on=1),
        lambda: balance_interval(interval(), RACK, 1, 2),
        lambda: balance_interval(interval(), RACK, -1, 0),
    ],
)
def test_invalid_inputs_rejected(action):
    with pytest.raises((TypeError, ValueError)):
        action()


def test_nonfinite_calculation_is_rejected():
    with pytest.raises(ValueError, match="finite"):
        balance_interval(interval(duration=10), Rack(1e308, 1, 0.8), 35, 0)


def test_sequence_handles_repeated_dst_hour_and_leap_day():
    zone = ZoneInfo("Europe/Zurich")
    repeated = datetime(2025, 10, 26, 2, tzinfo=zone, fold=0)
    repeated_second = datetime(2025, 10, 26, 2, tzinfo=zone, fold=1)
    after = datetime(2025, 10, 26, 3, tzinfo=zone)
    run = simulate(
        (
            ThermalInterval(repeated, repeated_second, 0, 0, True),
            ThermalInterval(repeated_second, after, 0, 0, True),
        ),
        RACK,
        35,
        0,
    )
    assert [r.electrical_energy_kwh for r in run.results] == [1, 1]
    leap = datetime(2024, 2, 29, tzinfo=UTC)
    assert balance_interval(interval(start=leap), RACK, 35, 0).electrical_energy_kwh == 1
