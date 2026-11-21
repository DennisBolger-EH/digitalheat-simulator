"""Simulate isolated site groups and aggregate their energy flows."""

from dataclasses import dataclass, fields
from math import fsum, isclose, isfinite

from digitalheat_simulator.domain.scenario import Interval, Scenario, SiteGroup
from digitalheat_simulator.domain.thermal import ABS_TOL_KWH, REL_TOL
from digitalheat_simulator.simulation.thermal import balance_flows


@dataclass(frozen=True)
class EnergyFlows:
    demand_kwh: float
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

    def validate_balances(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if not isfinite(value) or value < 0:
                raise ValueError(f"{field.name} must be finite and nonnegative")
        for name, left, right in (
            (
                "demand",
                self.demand_kwh,
                self.direct_supply_kwh + self.storage_discharge_kwh + self.backup_heat_kwh,
            ),
            (
                "recoverable",
                self.recoverable_heat_kwh,
                self.direct_supply_kwh + self.storage_charge_kwh + self.dumped_heat_kwh,
            ),
            (
                "storage",
                self.storage_closing_kwh,
                self.storage_opening_kwh + self.storage_charge_kwh - self.storage_discharge_kwh,
            ),
            ("gross", self.gross_heat_kwh, self.recoverable_heat_kwh + self.unrecovered_heat_kwh),
        ):
            if not isclose(left, right, rel_tol=REL_TOL, abs_tol=ABS_TOL_KWH):
                raise ValueError(f"{name} balance violated: {left} != {right} kWh")


@dataclass(frozen=True)
class SiteResult:
    site: SiteGroup
    per_site_flows: tuple[EnergyFlows, ...]


@dataclass(frozen=True)
class ScenarioIntervalResult:
    interval: Interval
    flows: EnergyFlows


@dataclass(frozen=True)
class ScenarioResult:
    scenario: Scenario
    sites: tuple[SiteResult, ...]
    intervals: tuple[ScenarioIntervalResult, ...]

    @property
    def site_counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for site in self.scenario.sites:
            result[site.consumer_kind] = result.get(site.consumer_kind, 0) + site.quantity
        return result

    @property
    def rack_count(self) -> int:
        return sum(
            site.quantity * sum(r.quantity for r in site.racks) for site in self.scenario.sites
        )


def _simulate_site(site: SiteGroup) -> SiteResult:
    state = site.initial_storage_kwh
    results = []
    for index, demand in enumerate(site.demand.points):
        duration = demand.interval.duration_hours
        electrical = fsum(
            r.quantity * r.rack.electrical_power_kw * duration
            for r in site.racks
            if r.operation[index].on
        )
        gross = fsum(
            r.quantity * r.rack.thermal_power_kw * duration
            for r in site.racks
            if r.operation[index].on
        )
        recovered = fsum(
            r.quantity * r.rack.thermal_power_kw * duration * r.rack.recovery_efficiency
            for r in site.racks
            if r.operation[index].on
        )
        unrecovered = fsum(
            r.quantity * r.rack.thermal_power_kw * duration * (1 - r.rack.recovery_efficiency)
            for r in site.racks
            if r.operation[index].on
        )
        direct, discharge, backup, charge, dumped, closing = balance_flows(
            demand.energy_kwh, recovered, site.storage_capacity_kwh, state
        )
        flows = EnergyFlows(
            demand.energy_kwh,
            electrical,
            gross,
            recovered,
            unrecovered,
            direct,
            state,
            charge,
            discharge,
            closing,
            dumped,
            backup,
        )
        flows.validate_balances()
        results.append(flows)
        state = closing
    return SiteResult(site, tuple(results))


def simulate_scenario(scenario: Scenario) -> ScenarioResult:
    sites = tuple(_simulate_site(site) for site in scenario.sites)
    intervals = []
    for index, demand in enumerate(scenario.sites[0].demand.points):
        totals = {
            field.name: fsum(
                getattr(site.per_site_flows[index], field.name) * site.site.quantity
                for site in sites
            )
            for field in fields(EnergyFlows)
        }
        flows = EnergyFlows(**totals)
        flows.validate_balances()
        intervals.append(ScenarioIntervalResult(demand.interval, flows))
    return ScenarioResult(scenario, sites, tuple(intervals))
