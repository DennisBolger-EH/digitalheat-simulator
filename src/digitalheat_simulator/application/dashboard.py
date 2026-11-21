"""UI-independent scenario preparation and result mapping."""

from dataclasses import dataclass, field, replace
from math import fsum, isfinite
from pathlib import Path

from digitalheat_simulator.application.optimization import ScenarioEvaluator
from digitalheat_simulator.application.optimization_demo import example
from digitalheat_simulator.data.pool_demand import pool_demand
from digitalheat_simulator.data.reference_house import load_weather, reconstruct_2025
from digitalheat_simulator.domain.parameters import Parameter, ParameterGroup, Provenance
from digitalheat_simulator.domain.scenario import (
    DemandPoint,
    OperationPoint,
    RackGroup,
    Scenario,
    SiteGroup,
)
from digitalheat_simulator.domain.thermal import Rack
from digitalheat_simulator.finance.model import Economics, reference_house_prices
from digitalheat_simulator.optimization.search import Evaluation, SearchResult, search
from digitalheat_simulator.simulation.scenario import ScenarioResult, simulate_scenario

WEATHER = Path(__file__).resolve().parents[3] / "case_materials" / "open-meteo-47.56N7.55E283m.csv"


@dataclass(frozen=True)
class Field:
    group: str
    identifier: str
    label: str
    unit: str
    value: float | int | None
    integer: bool = False
    provenance: Provenance | None = None


def _field(group, identifier, label, unit, value=None, integer=False, provenance=None):
    return Field(group, identifier, label, unit, value, integer, provenance)


def reference_fields() -> tuple[Field, ...]:
    prices = reference_house_prices("house")
    reference = Provenance("accepted M1 reference rack assumption", applicability="reference house")
    return (
        _field("Scenario", "houses", "Houses", "count", 1, True, reference),
        _field("Scenario", "pools", "Swimming pools", "count", 0, True),
        _field("Scenario", "racks", "Racks per house", "count", 1, True, reference),
        _field("Scenario", "pool_racks", "Racks per pool", "count", 0, True),
        _field("Scenario", "storage", "Storage capacity per house", "kWh", 35, False, reference),
        _field("Scenario", "initial", "Initial storage per house", "kWh", 0, False, reference),
        _field("Thermal consumers", "pool_storage", "Storage capacity per pool", "kWh", 0),
        _field("Thermal consumers", "pool_initial", "Initial storage per pool", "kWh", 0),
        _field(
            "Rack / Compute", "electrical", "Electrical power per rack", "kW", 1, False, reference
        ),
        _field(
            "Rack / Compute", "thermal", "Gross thermal power per rack", "kW", 1, False, reference
        ),
        _field(
            "Rack / Compute",
            "efficiency",
            "Heat recovery efficiency",
            "dimensionless",
            0.8,
            False,
            reference,
        ),
        _field("Rack / Compute", "capacity", "Compute capacity per rack", "TFLOP/s"),
        _field(
            "Energy",
            "electricity_price:house",
            "House electricity tariff",
            "CHF/kWh",
            prices.electricity.value,
            False,
            prices.electricity.provenance,
        ),
        _field(
            "Energy",
            "heat_value:house",
            "House useful-heat value",
            "CHF/kWh",
            prices.heat.value,
            False,
            prices.heat.provenance,
        ),
        _field(
            "Energy",
            "backup_price:house",
            "House backup-heat price",
            "CHF/kWh",
            prices.backup.value,
            False,
            prices.backup.provenance,
        ),
        _field("Energy", "electricity_price:pool", "Pool electricity tariff", "CHF/kWh"),
        _field("Energy", "heat_value:pool", "Pool useful-heat value", "CHF/kWh"),
        _field("Energy", "backup_price:pool", "Pool backup-heat price", "CHF/kWh"),
        *tuple(
            _field(group, f"{key}:{basis}", f"{prefix} {basis.replace('_', ' ')}", unit)
            for group, key, prefix, units in (
                (
                    "Hardware costs",
                    "hardware_costs",
                    "Hardware",
                    ("CHF", "CHF/rack", "CHF/site", "CHF/house", "CHF/pool"),
                ),
                (
                    "Installation costs",
                    "installation_costs",
                    "Installation",
                    ("CHF", "CHF/rack", "CHF/site", "CHF/house", "CHF/pool"),
                ),
                (
                    "Service / OPEX",
                    "running_service_costs",
                    "Service",
                    (
                        "CHF/year",
                        "CHF/rack/year",
                        "CHF/site/year",
                        "CHF/house/year",
                        "CHF/pool/year",
                    ),
                ),
                (
                    "Service / OPEX",
                    "other_opex",
                    "Other OPEX",
                    (
                        "CHF/year",
                        "CHF/rack/year",
                        "CHF/site/year",
                        "CHF/house/year",
                        "CHF/pool/year",
                    ),
                ),
            )
            for basis, unit in zip(
                ("fixed", "per_rack", "per_site", "per_house", "per_pool"), units, strict=True
            )
        ),
        _field("Finance", "lifetime_years", "Hardware lifetime", "year"),
        _field("Finance", "discount_rate", "Discount rate", "dimensionless"),
        _field("Compute income", "sold_server_hours", "Sold server-hours", "server-hour"),
        _field("Compute income", "price_per_server_hour", "Compute sale price", "CHF/server-hour"),
    )


@dataclass
class Configuration:
    mode: str = "reference"
    values: dict[str, float | int | None] = field(default_factory=dict)
    edited: set[str] = field(default_factory=set)
    pool_values: tuple[float, ...] | None = None
    pool_text: str = ""
    pool_source: str = ""
    objective: str = "economic"
    budget: int = 25
    ranges: dict[tuple[str, str], tuple[bool, float | None, float | None, float | None]] = field(
        default_factory=dict
    )
    dirty: bool = False
    revision: int = 0

    def __post_init__(self):
        if not self.values:
            self.values = {item.identifier: item.value for item in reference_fields()}

    def set(self, name: str, value: float | None) -> None:
        self.values[name] = value
        self.edited.add(name)
        self.mark_dirty()

    def mark_dirty(self) -> None:
        self.dirty = True
        self.revision += 1


def _parameter(identifier: str, value: float, unit: str, provenance: Provenance, integer=False):
    return Parameter(
        identifier,
        int(value) if integer else value,
        "integer" if integer else "number",
        "scenario",
        unit,
        provenance=provenance,
    )


def _source(config: Configuration, item: Field) -> Provenance:
    if item.identifier in config.edited or item.provenance is None:
        return Provenance("user input", unit=item.unit, applicability="configured scenario")
    return item.provenance


def validate(config: Configuration) -> None:
    for item in reference_fields():
        value = config.values.get(item.identifier)
        if value is None:
            if item.identifier in {
                "houses",
                "pools",
                "racks",
                "pool_racks",
                "storage",
                "initial",
                "electrical",
                "thermal",
                "efficiency",
                "pool_storage",
                "pool_initial",
            }:
                raise ValueError(f"{item.label} is required")
            continue
        if type(value) not in (int, float) or not isfinite(value) or value < 0:
            raise ValueError(f"{item.label} must be a nonnegative number ({item.unit})")
        if item.integer and int(value) != value:
            raise ValueError(f"{item.label} must be a whole number")
    if config.values["efficiency"] > 1:
        raise ValueError("Heat recovery efficiency must be between 0 and 1")
    for prefix in ("", "pool_"):
        if config.values[prefix + "initial"] > config.values[prefix + "storage"]:
            raise ValueError(
                f"{'Pool' if prefix else 'House'} initial storage must not exceed storage capacity"
            )
    if config.values["houses"] == 0 and config.values["pools"] == 0:
        raise ValueError("At least one house or swimming pool is required")
    if config.values["pools"] and (config.pool_values is None or not config.pool_source.strip()):
        raise ValueError("Swimming pools require a supplied hourly profile and its source")
    if type(config.budget) is not int or not 1 <= config.budget <= 625:
        raise ValueError("Candidate budget must be a whole number between 1 and 625")


def _ranges(
    config: Configuration, groups: tuple[ParameterGroup, ...]
) -> tuple[ParameterGroup, ...]:
    result = []
    for group in groups:
        params = []
        for parameter in group.parameters:
            setting = config.ranges.get((group.identifier, parameter.identifier))
            if setting:
                enabled, lower, upper, step = setting
                if enabled and (lower is None or upper is None or step is None):
                    raise ValueError(f"{parameter.identifier}: enter minimum, maximum and step")
                parameter = replace(
                    parameter, optimizable=enabled, minimum=lower, maximum=upper, step=step
                )
            params.append(parameter)
        result.append(replace(group, parameters=tuple(params)))
    return tuple(result)


def prepare(config: Configuration):
    if config.mode == "synthetic":
        scenario, economics, groups = example()

        def synthetic_parameter(group, parameter):
            key = f"synthetic:{group.identifier}:{parameter.identifier}"
            value = config.values.get(key, parameter.value)
            if value is None or type(value) not in (int, float) or not isfinite(value):
                raise ValueError(f"{parameter.identifier} requires a numeric value")
            if parameter.data_type == "integer":
                if int(value) != value:
                    raise ValueError(f"{parameter.identifier} must be a whole number")
                value = int(value)
            provenance = (
                Provenance("user input in synthetic demonstration", unit=parameter.unit)
                if key in config.edited
                else parameter.provenance
            )
            return replace(parameter, value=value, provenance=provenance)

        groups = tuple(
            replace(
                g,
                parameters=tuple(synthetic_parameter(g, p) for p in g.parameters),
            )
            for g in groups
        )
        return scenario, economics, _ranges(config, groups), None
    validate(config)
    samples, _, _ = load_weather(WEATHER)
    reconstructed = reconstruct_2025(WEATHER, (True,) * len(samples))
    demand = reconstructed.as_demand_series()
    v = config.values
    rack = Rack(v["electrical"], v["thermal"], v["efficiency"])
    operation = tuple(OperationPoint(p.interval, True) for p in demand.points)
    sites = []
    if v["houses"]:
        sites.append(
            SiteGroup(
                "house",
                "house",
                int(v["houses"]),
                demand,
                (RackGroup("rack", rack, int(v["racks"]), operation),),
                v["storage"],
                v["initial"],
            )
        )
    if v["pools"]:
        if len(config.pool_values) != len(demand.points):
            raise ValueError(
                f"Pool profile must contain exactly {len(demand.points)} hourly kWh values"
            )
        provenance = Provenance(config.pool_source, unit="kWh", applicability="user-supplied pool")
        pool = pool_demand(
            "pool",
            tuple(
                DemandPoint(point.interval, value)
                for point, value in zip(demand.points, config.pool_values, strict=True)
            ),
            provenance,
        )
        sites.append(
            SiteGroup(
                "pool",
                "pool",
                int(v["pools"]),
                pool,
                (RackGroup("rack", rack, int(v["pool_racks"]), operation),),
                v["pool_storage"],
                v["pool_initial"],
            )
        )
    scenario = Scenario(tuple(sites))
    fields = {item.identifier: item for item in reference_fields()}
    groups: dict[str, list[Parameter]] = {}

    def add(group, identifier, source_id):
        value = v[source_id]
        if value is not None:
            item = fields[source_id]
            groups.setdefault(group, []).append(
                _parameter(identifier, value, item.unit, _source(config, item), item.integer)
            )

    for site in sites:
        name = site.identifier
        add("quantities", f"site_count:{name}", "houses" if name == "house" else "pools")
        add("quantities", f"rack_count:{name}:rack", "racks" if name == "house" else "pool_racks")
        add("storage", f"capacity_kwh:{name}", "storage" if name == "house" else "pool_storage")
        for target, source in (
            ("electrical_power_kw", "electrical"),
            ("thermal_power_kw", "thermal"),
            ("recovery_efficiency", "efficiency"),
        ):
            add("rack_technical", f"{target}:{name}:rack", source)
        for key in ("electricity_price", "heat_value", "backup_price"):
            add("energy_costs", f"{key}:{name}", f"{key}:{name}")
    for item in fields.values():
        if item.group in ("Hardware costs", "Installation costs", "Service / OPEX"):
            name, basis = item.identifier.split(":")
            group = "running_service_costs" if name == "other_opex" else name
            prefix = (
                "other_"
                if name == "other_opex"
                else "service_"
                if name == "running_service_costs"
                else ""
            )
            add(group, prefix + basis, item.identifier)
    for key in ("lifetime_years", "discount_rate"):
        add("finance_parameters", key, key)
    for key in ("sold_server_hours", "price_per_server_hour"):
        add("compute_income", key, key)
    grouped = tuple(ParameterGroup(key, tuple(params)) for key, params in groups.items())
    return scenario, Economics(()), _ranges(config, grouped), reconstructed


@dataclass(frozen=True)
class DashboardResult:
    evaluation: Evaluation
    thermal: ScenarioResult
    space_heat_kwh: float | None
    hot_water_kwh: float | None
    installed_capacity_tflop_per_s: float | None


def run_simulation(config: Configuration) -> DashboardResult:
    scenario, economics, groups, reference = prepare(config)
    result = ScenarioEvaluator(scenario, economics)(groups)
    if result.metrics is None:
        raise ValueError("; ".join(c.detail for c in result.constraints if not c.satisfied))
    thermal = simulate_scenario(result.metrics.scenario)
    house_count = sum(
        site.quantity for site in thermal.scenario.sites if site.identifier == "house"
    )
    return DashboardResult(
        result,
        thermal,
        fsum(i.space_demand_kwh for i in reference.intervals) * house_count if reference else None,
        fsum(i.hot_water_demand_kwh for i in reference.intervals) * house_count
        if reference
        else None,
        thermal.rack_count * config.values["capacity"]
        if config.mode == "reference" and config.values["capacity"] is not None
        else None,
    )


def run_optimization(config: Configuration) -> SearchResult:
    if type(config.budget) is not int or not 1 <= config.budget <= 625:
        raise ValueError("Candidate budget must be a whole number between 1 and 625")
    scenario, economics, groups, _ = prepare(config)
    return search(
        groups, ScenarioEvaluator(scenario, economics), config.objective, budget=config.budget
    )
