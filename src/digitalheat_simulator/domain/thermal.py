"""Format-independent thermal inputs and results in explicitly named SI-derived units."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isclose, isfinite

from digitalheat_simulator.domain.units import convert

ABS_TOL_KWH = 1e-9
REL_TOL = 1e-12


def _nonnegative(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a finite nonnegative number")
    if not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")


def power_kw(value: float, unit: str) -> float:
    """Convert explicitly supplied power to kW; incompatible dimensions fail."""
    result = convert(value, unit, "kW")
    _nonnegative("power", result)
    return result


def energy_kwh(value: float, unit: str) -> float:
    """Convert explicitly supplied energy to kWh; incompatible dimensions fail."""
    result = convert(value, unit, "kWh")
    _nonnegative("energy", result)
    return result


@dataclass(frozen=True)
class Rack:
    electrical_power_kw: float
    thermal_power_kw: float
    recovery_efficiency: float

    def __post_init__(self) -> None:
        _nonnegative("electrical_power_kw", self.electrical_power_kw)
        _nonnegative("thermal_power_kw", self.thermal_power_kw)
        _nonnegative("recovery_efficiency", self.recovery_efficiency)
        if self.recovery_efficiency > 1:
            raise ValueError("recovery_efficiency must not exceed 1")


@dataclass(frozen=True)
class ThermalInterval:
    start: datetime
    end: datetime
    space_demand_kwh: float
    hot_water_demand_kwh: float
    rack_on: bool

    def __post_init__(self) -> None:
        if self.start.utcoffset() is None or self.end.utcoffset() is None:
            raise ValueError("interval bounds must be timezone-aware")
        if self.end.astimezone(UTC) <= self.start.astimezone(UTC):
            raise ValueError("interval end must follow start")
        _nonnegative("space_demand_kwh", self.space_demand_kwh)
        _nonnegative("hot_water_demand_kwh", self.hot_water_demand_kwh)
        if type(self.rack_on) is not bool:
            raise ValueError("rack_on must be a boolean")

    @property
    def duration_hours(self) -> float:
        return (self.end.astimezone(UTC) - self.start.astimezone(UTC)) / timedelta(hours=1)


@dataclass(frozen=True)
class ThermalResult:
    interval: ThermalInterval
    electrical_energy_kwh: float
    gross_heat_kwh: float
    recoverable_heat_kwh: float
    unrecovered_heat_kwh: float
    direct_supply_kwh: float
    storage_opening_kwh: float
    storage_charge_kwh: float
    storage_discharge_kwh: float
    storage_closing_kwh: float
    dumped_heat_kwh: float
    backup_heat_kwh: float

    @property
    def demand_kwh(self) -> float:
        return self.interval.space_demand_kwh + self.interval.hot_water_demand_kwh

    @property
    def house_supply_kwh(self) -> float:
        return self.direct_supply_kwh + self.storage_discharge_kwh

    def validate_balances(self) -> None:
        for name in (
            "electrical_energy_kwh",
            "gross_heat_kwh",
            "recoverable_heat_kwh",
            "unrecovered_heat_kwh",
            "direct_supply_kwh",
            "storage_opening_kwh",
            "storage_charge_kwh",
            "storage_discharge_kwh",
            "storage_closing_kwh",
            "dumped_heat_kwh",
            "backup_heat_kwh",
            "demand_kwh",
        ):
            _nonnegative(name, getattr(self, name))
        balances = (
            ("house demand", self.demand_kwh, self.house_supply_kwh + self.backup_heat_kwh),
            (
                "recoverable heat",
                self.recoverable_heat_kwh,
                self.direct_supply_kwh + self.storage_charge_kwh + self.dumped_heat_kwh,
            ),
            (
                "storage",
                self.storage_closing_kwh,
                self.storage_opening_kwh + self.storage_charge_kwh - self.storage_discharge_kwh,
            ),
        )
        for name, actual, expected in balances:
            if not isclose(actual, expected, rel_tol=REL_TOL, abs_tol=ABS_TOL_KWH):
                raise ValueError(f"{name} energy balance violated: {actual} != {expected} kWh")


@dataclass(frozen=True)
class ThermalRun:
    rack: Rack
    storage_capacity_kwh: float
    initial_storage_kwh: float
    results: tuple[ThermalResult, ...]
