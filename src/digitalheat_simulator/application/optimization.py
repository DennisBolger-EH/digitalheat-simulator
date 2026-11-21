"""Bind project parameters to M2/M3 scenarios and M5 economics."""

from dataclasses import dataclass, replace
from math import fsum

from digitalheat_simulator.domain.compute import ComputeRack, Job
from digitalheat_simulator.domain.parameters import Parameter, ParameterGroup
from digitalheat_simulator.domain.scenario import Scenario
from digitalheat_simulator.finance.model import (
    Economics,
    SitePrices,
    economics_from_groups,
    evaluate,
)
from digitalheat_simulator.optimization.search import Constraint, Evaluation, Metrics
from digitalheat_simulator.simulation.compute_thermal import IntegratedResult
from digitalheat_simulator.simulation.scenario import ScenarioResult, simulate_scenario
from digitalheat_simulator.workload.scheduler import ScheduleResult, schedule


@dataclass(frozen=True)
class Capacity:
    site: str
    rack_group: str
    installed_tflop_per_s: float
    available_tflop_per_s: float


_COST_FIELDS = {
    "hardware_costs": {"fixed", "per_rack", "per_site", "per_house", "per_pool", "no_costs"},
    "installation_costs": {"fixed", "per_rack", "per_site", "per_house", "per_pool", "no_costs"},
    "running_service_costs": {
        f"{prefix}{name}"
        for prefix in ("service_", "other_")
        for name in ("fixed", "per_rack", "per_site", "per_house", "per_pool", "no_costs")
    },
    "finance_parameters": {"lifetime_years", "discount_rate"},
    "compute_income": {"sold_server_hours", "price_per_server_hour"},
}


class CandidateInputError(ValueError):
    """A candidate cannot be mapped to the supplied scenario."""


class ScenarioEvaluator:
    """Evaluate immutable candidate groups using the existing physical and finance models.

    Site/rack count bindings use per-site rack counts. Optional scheduled mode
    expands site groups and maps jobs' eligible group IDs to individual sites.
    """

    def __init__(
        self,
        scenario: Scenario,
        economics: Economics,
        *,
        jobs: tuple[Job, ...] | None = None,
        capacities: tuple[Capacity, ...] = (),
        require_work: bool = True,
        require_deadlines: bool = True,
        assumptions: tuple[str, ...] = (),
    ) -> None:
        self.scenario = scenario
        self.economics = economics
        self.jobs = jobs
        self.capacities = capacities
        self.require_work = require_work
        self.require_deadlines = require_deadlines
        self.assumptions = assumptions
        self._cache: dict[
            tuple[Scenario, tuple[Job, ...] | None, tuple[Capacity, ...]],
            ScenarioResult | ScheduleResult,
        ] = {}
        self.cache_hits = 0
        if len({(c.site, c.rack_group) for c in capacities}) != len(capacities):
            raise ValueError("duplicate capacity binding")
        identifiers = {site.identifier for site in scenario.sites}
        price_sites = [price.site_identifier for price in economics.site_prices]
        if len(set(price_sites)) != len(price_sites) or set(price_sites) - identifiers:
            raise ValueError("site prices must reference distinct known sites")
        if jobs is not None and any(set(job.eligible_sites) - identifiers for job in jobs):
            raise ValueError("job eligibility references an unknown site group")

    def _bind(self, groups: tuple[ParameterGroup, ...]) -> Scenario:
        sites = {site.identifier: site for site in self.scenario.sites}
        for group in groups:
            for parameter in group.parameters:
                parts = parameter.identifier.split(":")
                physical = group.identifier in ("quantities", "storage", "rack_technical")
                if not physical:
                    recognized = parameter.identifier in _COST_FIELDS.get(group.identifier, set())
                    recognized |= group.identifier == "energy_costs" and (
                        len(parts) == 2
                        and parts[0] in ("electricity_price", "heat_value", "backup_price")
                        and parts[1] in sites
                    )
                    if (
                        parameter.enabled is not False
                        and parameter.optimizable is True
                        and parameter.data_type in ("integer", "number")
                        and parameter.minimum is not None
                        and parameter.maximum is not None
                        and parameter.step is not None
                        and not recognized
                    ):
                        raise CandidateInputError(
                            f"unbound optimizable parameter: {group.identifier}/{parameter.identifier}"
                        )
                    continue
                if parameter.enabled is False:
                    continue
                if len(parts) < 2 or parts[1] not in sites:
                    raise ValueError(f"unknown physical parameter binding: {parameter.identifier}")
                if parameter.provenance is None:
                    raise ValueError(f"{parameter.identifier} requires provenance")
                site = sites[parts[1]]
                if (
                    group.identifier == "quantities"
                    and parts[0] == "site_count"
                    and len(parts) == 2
                ):
                    self._check(parameter, "integer", "count")
                    if parameter.value < 0:
                        raise ValueError("site count must be nonnegative")
                    # Preserve zero until all bindings have been applied.
                    sites[parts[1]] = (
                        (site, parameter.value)
                        if not isinstance(site, tuple)
                        else (site[0], parameter.value)
                    )
                    continue
                if isinstance(site, tuple):
                    actual, count = site
                else:
                    actual, count = site, None
                if group.identifier == "storage" and parts[0] == "capacity_kwh" and len(parts) == 2:
                    self._check(parameter, "number", "kWh")
                    actual = replace(actual, storage_capacity_kwh=parameter.value)
                elif len(parts) == 3 and parts[2] in {rack.identifier for rack in actual.racks}:
                    racks = []
                    for rack in actual.racks:
                        if rack.identifier == parts[2]:
                            if group.identifier == "quantities" and parts[0] == "rack_count":
                                self._check(parameter, "integer", "count")
                                rack = replace(rack, quantity=parameter.value)
                            elif group.identifier == "rack_technical" and parts[0] in (
                                "electrical_power_kw",
                                "thermal_power_kw",
                                "recovery_efficiency",
                            ):
                                unit = (
                                    "dimensionless" if parts[0] == "recovery_efficiency" else "kW"
                                )
                                self._check(parameter, "number", unit)
                                rack = replace(
                                    rack, rack=replace(rack.rack, **{parts[0]: parameter.value})
                                )
                            else:
                                raise ValueError(
                                    f"unknown physical parameter binding: {parameter.identifier}"
                                )
                        racks.append(rack)
                    actual = replace(actual, racks=tuple(racks))
                else:
                    raise ValueError(f"unknown physical parameter binding: {parameter.identifier}")
                sites[parts[1]] = (actual, count) if count is not None else actual
        result = []
        for item in sites.values():
            if isinstance(item, tuple):
                site, count = item
                if count:
                    result.append(replace(site, quantity=count))
            else:
                result.append(item)
        return Scenario(tuple(result))

    @staticmethod
    def _check(parameter: Parameter, kind: str, unit: str) -> None:
        if (
            parameter.data_type not in (("integer", "number") if kind == "number" else ("integer",))
            or parameter.unit != unit
        ):
            raise ValueError(f"{parameter.identifier} requires {kind} in {unit}")

    def _scheduled(self, scenario: Scenario) -> ScheduleResult:
        capacities = {(c.site, c.rack_group): c for c in self.capacities}
        expanded = []
        racks = []
        ids: dict[str, tuple[str, ...]] = {}
        for site in scenario.sites:
            ids[site.identifier] = tuple(
                site.identifier if site.quantity == 1 else f"{site.identifier}#{i + 1}"
                for i in range(site.quantity)
            )
            for identifier in ids[site.identifier]:
                expanded.append(replace(site, identifier=identifier, quantity=1))
                for rack_group in site.racks:
                    capacity = capacities.get((site.identifier, rack_group.identifier))
                    if capacity is None and rack_group.quantity:
                        raise CandidateInputError(
                            f"compute capacity missing for {site.identifier}/{rack_group.identifier}"
                        )
                    for i in range(rack_group.quantity):
                        racks.append(
                            ComputeRack(
                                f"{rack_group.identifier}#{i + 1}",
                                identifier,
                                rack_group.rack,
                                capacity.installed_tflop_per_s,
                                capacity.available_tflop_per_s,
                            )
                        )
        if len({site.identifier for site in expanded}) != len(expanded):
            raise CandidateInputError("expanded site identifiers collide")
        jobs = []
        for job in self.jobs:
            known = {site.identifier for site in self.scenario.sites}
            if set(job.eligible_sites) - known:
                raise ValueError("job eligibility references an unknown site group")
            eligible = tuple(
                identifier
                for original in job.eligible_sites
                for identifier in ids.get(original, ())
            )
            if not eligible:
                raise CandidateInputError(f"no eligible sites remain for job {job.identifier}")
            jobs.append(replace(job, eligible_sites=eligible))
        return schedule(Scenario(tuple(expanded)), tuple(jobs), tuple(racks))

    def _economics(
        self, groups: tuple[ParameterGroup, ...], scenario: Scenario, grouped: Scenario
    ) -> Economics:
        names = {group.identifier for group in groups}
        original_sites = tuple(site.identifier for site in self.scenario.sites)
        enabled_groups = tuple(
            replace(group, parameters=tuple(p for p in group.parameters if p.enabled is not False))
            for group in groups
        )
        mapped = economics_from_groups(enabled_groups, original_sites)
        base_prices = {price.site_identifier: price for price in self.economics.site_prices}
        mapped_prices = {price.site_identifier: price for price in mapped.site_prices}
        owners = {
            identifier: site.identifier
            for site in grouped.sites
            for identifier in (
                (site.identifier,)
                if self.jobs is None or site.quantity == 1
                else tuple(f"{site.identifier}#{i + 1}" for i in range(site.quantity))
            )
        }
        prices = []
        for site in scenario.sites:
            original = owners.get(site.identifier)
            if original is None:
                raise ValueError(f"no price source for site {site.identifier}")
            base = base_prices.get(original, SitePrices(original))
            updates = mapped_prices[original]
            prices.append(
                replace(
                    base,
                    site_identifier=site.identifier,
                    electricity=updates.electricity
                    if updates.electricity is not None
                    else base.electricity,
                    heat=updates.heat if updates.heat is not None else base.heat,
                    backup=updates.backup if updates.backup is not None else base.backup,
                )
            )
        changes = {"site_prices": tuple(prices)}
        for name, attributes in (
            ("hardware_costs", ("hardware",)),
            ("installation_costs", ("installation",)),
            ("running_service_costs", ("service", "other_annual_opex")),
            ("finance_parameters", ("lifetime_years", "discount_rate")),
            ("compute_income", ("sold_server_hours", "compute_price")),
        ):
            if name in names:
                for attr in attributes:
                    value = getattr(mapped, attr)
                    if value is not None:
                        changes[attr] = value
        return replace(self.economics, **changes)

    def __call__(self, groups: tuple[ParameterGroup, ...]) -> Evaluation:
        try:
            scenario = self._bind(groups)
        except ValueError as exc:
            return Evaluation(
                None, (Constraint("valid inputs", False, str(exc)),), self.assumptions
            )
        key = (scenario, self.jobs, self.capacities)
        if key in self._cache:
            physical = self._cache[key]
            self.cache_hits += 1
        else:
            try:
                physical = (
                    self._scheduled(scenario)
                    if self.jobs is not None
                    else simulate_scenario(scenario)
                )
            except CandidateInputError as exc:
                return Evaluation(
                    None, (Constraint("valid inputs", False, str(exc)),), self.assumptions
                )
            self._cache[key] = physical
        integrated: IntegratedResult | None = (
            physical.integrated if isinstance(physical, ScheduleResult) else None
        )
        thermal = integrated.thermal if integrated is not None else physical
        try:
            economics = evaluate(
                integrated if integrated is not None else thermal,
                self._economics(groups, thermal.scenario, scenario),
            )
        except ValueError as exc:
            return Evaluation(
                None, (Constraint("valid inputs", False, str(exc)),), self.assumptions
            )
        constraints = [Constraint("valid inputs and local thermal balances", True, "validated")]
        delivered = remaining = utilization = None
        completed = missed = None
        if integrated is not None:
            delivered = fsum(p.completed_work_tflop for p in integrated.progress)
            remaining = fsum(p.remaining_work_tflop for p in integrated.progress)
            capacity = fsum(
                r.rack.available_capacity_tflop_per_s * r.period_seconds for r in integrated.racks
            )
            utilization = delivered / capacity if capacity else None
            completed = sum(outcome.completion is not None for outcome in physical.outcomes)
            missed = sum(outcome.deadline_missed for outcome in physical.outcomes)
            if self.require_work:
                constraints.append(
                    Constraint(
                        "required work",
                        completed == len(physical.outcomes),
                        "all required jobs completed"
                        if completed == len(physical.outcomes)
                        else "required work incomplete under evaluated schedule",
                    )
                )
            if self.require_deadlines:
                constraints.append(
                    Constraint(
                        "deadlines",
                        missed == 0,
                        "all deadlines met"
                        if missed == 0
                        else "deadline missed under evaluated schedule",
                    )
                )
        flows = tuple(row.flows for row in thermal.intervals)
        useful = economics.useful_heat_kwh.value
        demand = fsum(flow.demand_kwh for flow in flows)
        metrics = Metrics(
            thermal.scenario,
            self.scenario,
            tuple(progress.job for progress in integrated.progress) if integrated else None,
            tuple(usage.rack for usage in integrated.racks) if integrated else None,
            economics.annual,
            useful,
            fsum(flow.dumped_heat_kwh for flow in flows),
            fsum(flow.backup_heat_kwh for flow in flows),
            useful / demand if useful is not None and demand else None,
            fsum(flow.electrical_energy_kwh for flow in flows),
            delivered,
            remaining,
            utilization,
            completed,
            missed,
            economics,
        )
        return Evaluation(metrics, tuple(constraints), self.assumptions)
