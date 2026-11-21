"""Deterministic thermal balance independent of input formats and presentation."""

from collections.abc import Iterable
from datetime import UTC
from math import isfinite

from digitalheat_simulator.domain.thermal import Rack, ThermalInterval, ThermalResult, ThermalRun


def _storage(capacity_kwh: float, state_kwh: float) -> None:
    for name, value in (("capacity", capacity_kwh), ("storage state", state_kwh)):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(value)
            or value < 0
        ):
            raise ValueError(f"{name} must be a finite nonnegative number in kWh")
    if state_kwh > capacity_kwh:
        raise ValueError("storage state exceeds capacity")


def balance_interval(
    interval: ThermalInterval, rack: Rack, capacity_kwh: float, opening_kwh: float
) -> ThermalResult:
    _storage(capacity_kwh, opening_kwh)
    duration = interval.duration_hours
    electrical = rack.electrical_power_kw * duration if interval.rack_on else 0.0
    gross = rack.thermal_power_kw * duration if interval.rack_on else 0.0
    recovered = gross * rack.recovery_efficiency
    demand = interval.space_demand_kwh + interval.hot_water_demand_kwh
    direct = min(demand, recovered)
    discharge = min(opening_kwh, demand - direct)
    backup = demand - direct - discharge
    charge = min(recovered - direct, capacity_kwh - opening_kwh)
    dumped = recovered - direct - charge
    closing = opening_kwh + charge - discharge
    result = ThermalResult(
        interval=interval,
        electrical_energy_kwh=electrical,
        gross_heat_kwh=gross,
        recoverable_heat_kwh=recovered,
        unrecovered_heat_kwh=gross - recovered,
        direct_supply_kwh=direct,
        storage_opening_kwh=opening_kwh,
        storage_charge_kwh=charge,
        storage_discharge_kwh=discharge,
        storage_closing_kwh=closing,
        dumped_heat_kwh=dumped,
        backup_heat_kwh=backup,
    )
    result.validate_balances()
    _storage(capacity_kwh, closing)
    return result


def simulate(
    intervals: Iterable[ThermalInterval], rack: Rack, capacity_kwh: float, initial_kwh: float
) -> ThermalRun:
    _storage(capacity_kwh, initial_kwh)
    state = initial_kwh
    results = []
    previous_end = None
    for interval in intervals:
        start = interval.start.astimezone(UTC)
        if previous_end is not None and start != previous_end:
            raise ValueError("intervals must be contiguous and in elapsed-time order")
        result = balance_interval(interval, rack, capacity_kwh, state)
        results.append(result)
        previous_end = interval.end.astimezone(UTC)
        state = result.storage_closing_kwh
    if not results:
        raise ValueError("at least one interval is required")
    return ThermalRun(rack, capacity_kwh, initial_kwh, tuple(results))
