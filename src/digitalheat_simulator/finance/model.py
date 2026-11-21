"""Site-local economics for supplied simulation results, in CHF and kWh."""

from dataclasses import dataclass
from datetime import datetime
from math import expm1, fsum, isfinite, log1p
from typing import Literal
from zoneinfo import ZoneInfo

from digitalheat_simulator.domain.compute import ComputeRack
from digitalheat_simulator.domain.parameters import Parameter, ParameterGroup, Provenance
from digitalheat_simulator.domain.scenario import Interval
from digitalheat_simulator.simulation.compute_thermal import (
    IntegratedResult,
    RackOnInterval,
    simulate_rack_intervals,
)
from digitalheat_simulator.simulation.scenario import ScenarioResult, simulate_scenario
from digitalheat_simulator.workload.execution import union_seconds


@dataclass(frozen=True)
class Amount:
    value: float | None
    reason: str | None = None
    classification: Literal["derived", "configured", "unavailable"] = "derived"

    @classmethod
    def missing(cls, reason: str) -> "Amount":
        return cls(None, reason, "unavailable")


def _number(parameter: Parameter, unit: str) -> float:
    if (
        parameter.data_type not in ("integer", "number")
        or parameter.unit != unit
        or parameter.enabled is False
        or parameter.provenance is None
    ):
        raise ValueError(f"{parameter.identifier} requires enabled numeric {unit} with provenance")
    value = float(parameter.value)
    if not isfinite(value) or value < 0:
        raise ValueError(f"{parameter.identifier} must be finite and nonnegative")
    return value


@dataclass(frozen=True)
class RatePoint:
    interval: Interval
    rate: Parameter


@dataclass(frozen=True)
class SitePrices:
    site_identifier: str
    electricity: Parameter | tuple[RatePoint, ...] | None = None
    heat: Parameter | tuple[RatePoint, ...] | None = None
    backup: Parameter | tuple[RatePoint, ...] | None = None
    heat_mode: Literal["avoided", "revenue"] = "avoided"
    opening_storage_is_server_heat: bool = False

    def __post_init__(self) -> None:
        if not self.site_identifier.strip():
            raise ValueError("site identifier is required")
        if self.heat_mode not in ("avoided", "revenue"):
            raise ValueError("heat mode must be avoided or revenue")
        if type(self.opening_storage_is_server_heat) is not bool:
            raise ValueError("opening storage attribution must be boolean")


@dataclass(frozen=True)
class CostLine:
    """Fixed or per-unit cost, with inclusive quantity bounds for an explicit tier."""

    price: Parameter
    basis: Literal["scenario", "rack", "site", "house", "pool"]
    minimum_quantity: int = 0
    maximum_quantity: int | None = None

    def __post_init__(self) -> None:
        if self.basis not in ("scenario", "rack", "site", "house", "pool"):
            raise ValueError("unsupported cost basis")
        if (
            type(self.minimum_quantity) is not int
            or self.minimum_quantity < 0
            or (
                self.maximum_quantity is not None
                and (
                    type(self.maximum_quantity) is not int
                    or self.maximum_quantity < self.minimum_quantity
                )
            )
        ):
            raise ValueError("invalid cost quantity bounds")


@dataclass(frozen=True)
class Economics:
    site_prices: tuple[SitePrices, ...]
    hardware: tuple[CostLine, ...] | None = None
    installation: tuple[CostLine, ...] | None = None
    service: tuple[CostLine, ...] | None = None
    other_annual_opex: tuple[CostLine, ...] | None = None
    lifetime_years: Parameter | None = None
    discount_rate: Parameter | None = None
    sold_server_hours: Parameter | None = None
    compute_price: Parameter | None = None


def economics_from_groups(
    groups: tuple[ParameterGroup, ...], site_identifiers: tuple[str, ...]
) -> Economics:
    """Map named economic groups to inputs without closing the project group model.

    Absent cost inputs mean unknown. An explicit provenance-bearing boolean
    ``no_costs`` (or ``service_no_costs``/``other_no_costs``) records zero.
    Other parameter groups are left untouched.
    """
    by_name = {group.identifier: group for group in groups}
    if len(by_name) != len(groups):
        raise ValueError("parameter group identifiers must be unique")
    if len(set(site_identifiers)) != len(site_identifiers):
        raise ValueError("site identifiers must be unique")

    def fields(name: str) -> dict[str, Parameter]:
        group = by_name.get(name)
        return {} if group is None else {p.identifier: p for p in group.parameters}

    def cost_lines(group_name: str, prefix: str = "") -> tuple[CostLine, ...] | None:
        if group_name not in by_name:
            return None
        values = fields(group_name)
        recognized = {
            "fixed": "scenario",
            "per_rack": "rack",
            "per_site": "site",
            "per_house": "house",
            "per_pool": "pool",
        }
        selected = tuple(
            CostLine(values[prefix + key], basis)
            for key, basis in recognized.items()
            if prefix + key in values
        )
        no_costs = values.get(prefix + "no_costs")
        if no_costs is not None:
            if (
                no_costs.data_type != "boolean"
                or no_costs.value is not True
                or no_costs.enabled is False
                or no_costs.provenance is None
                or selected
            ):
                raise ValueError(f"{prefix}no_costs must explicitly confirm zero costs")
            return ()
        return selected or None

    energy = fields("energy_costs")
    compute = fields("compute_income")
    finance = fields("finance_parameters")
    prices = tuple(
        SitePrices(
            identifier,
            electricity=energy.get(f"electricity_price:{identifier}"),
            heat=energy.get(f"heat_value:{identifier}"),
            backup=energy.get(f"backup_price:{identifier}"),
        )
        for identifier in site_identifiers
    )
    return Economics(
        site_prices=prices,
        hardware=cost_lines("hardware_costs"),
        installation=cost_lines("installation_costs"),
        service=cost_lines("running_service_costs", "service_"),
        other_annual_opex=cost_lines("running_service_costs", "other_"),
        lifetime_years=finance.get("lifetime_years"),
        discount_rate=finance.get("discount_rate"),
        sold_server_hours=compute.get("sold_server_hours"),
        compute_price=compute.get("price_per_server_hour"),
    )


@dataclass(frozen=True)
class EconomicResult:
    annual: bool
    electrical_energy_basis: Literal["simulated", "estimated"]
    rack_hours: Amount
    sold_server_hours: Amount
    useful_heat_kwh: Amount
    dumped_heat_kwh: float
    backup_heat_kwh: float
    hardware_capex_chf: Amount
    installation_capex_chf: Amount
    capex_chf: Amount
    annualized_capex_chf: Amount
    electricity_cost_chf: Amount
    service_cost_chf: Amount
    other_opex_chf: Amount
    backup_cost_chf: Amount
    useful_heat_value_chf: Amount
    avoided_heat_cost_chf: Amount
    heat_revenue_chf: Amount
    opex_chf: Amount
    compute_income_chf: Amount
    net_cash_contribution_chf: Amount
    annualized_total_cost_chf: Amount
    case_break_even_chf_per_server_hour: Amount
    full_cost_break_even_chf_per_server_hour: Amount
    inputs: Economics


def reference_house_prices(site_identifier: str) -> SitePrices:
    tariff = Parameter(
        "electricity_price",
        0.3325,
        "number",
        "unit",
        "CHF/kWh",
        provenance=Provenance(
            "case_materials/CostsForElectricalPowerInTotal.png; ElCom 2026 IWB Basel H4 Standard",
            unit="CHF/kWh",
            applicability="Basel reference house",
            transformation="33.25 Rp/kWh divided by 100; access date unknown",
        ),
    )
    heat = Parameter(
        "heat_value",
        0.3325 / 2.5,
        "number",
        "unit",
        "CHF/kWh",
        provenance=Provenance(
            "sprintd case heat-pump efficiency 2.5 and supplied ElCom tariff screenshot",
            unit="CHF/kWh",
            applicability="Basel reference house",
            transformation="0.3325 CHF/kWh / 2.5; access dates unknown",
        ),
    )
    return SitePrices(site_identifier, electricity=tariff, heat=heat, backup=heat)


def _combine(label: str, *items: Amount) -> Amount:
    missing = [item.reason for item in items if item.value is None]
    if missing:
        return Amount.missing(f"{label}: " + "; ".join(str(item) for item in missing))
    return Amount(fsum(item.value for item in items if item.value is not None))


def _rates(
    rate: Parameter | tuple[RatePoint, ...] | None,
    intervals: tuple[Interval, ...],
    label: str,
) -> tuple[float, ...] | None:
    if rate is None:
        return None
    if isinstance(rate, Parameter):
        return (_number(rate, "CHF/kWh"),) * len(intervals)
    if not isinstance(rate, tuple) or len(rate) != len(intervals):
        raise ValueError(f"{label} rates must match all intervals")
    values = []
    for point, interval in zip(rate, intervals, strict=True):
        if not isinstance(point, RatePoint) or point.interval.key() != interval.key():
            raise ValueError(f"{label} rate interval mismatch")
        values.append(_number(point.rate, "CHF/kWh"))
    return tuple(values)


def _cost(
    lines: tuple[CostLine, ...] | None, result: ScenarioResult, label: str, annual: bool = False
) -> Amount:
    if lines is None:
        return Amount.missing(f"{label} inputs missing")
    if not isinstance(lines, tuple):
        raise TypeError("cost lines must be a tuple or None")
    counts = {
        "scenario": 1,
        "rack": result.rack_count,
        "site": sum(site.quantity for site in result.scenario.sites),
        "house": result.site_counts.get("house", 0),
        "pool": result.site_counts.get("pool", 0),
    }
    values = []
    for line in lines:
        count = counts[line.basis]
        unit = "CHF" if line.basis == "scenario" else f"CHF/{line.basis}"
        if annual:
            unit += "/year"
        price = _number(line.price, unit)
        if count >= line.minimum_quantity and (
            line.maximum_quantity is None or count <= line.maximum_quantity
        ):
            values.append(price * count)
    return Amount(fsum(values))


def _annual(result: ScenarioResult) -> bool:
    zone = ZoneInfo("Europe/Zurich")
    points = result.scenario.sites[0].demand.points
    start = points[0].interval.start.astimezone(zone)
    end = points[-1].interval.end.astimezone(zone)
    return start == datetime(start.year, 1, 1, tzinfo=zone) and end == datetime(
        start.year + 1, 1, 1, tzinfo=zone
    )


def _rack_hours(
    result: ScenarioResult,
    integrated: IntegratedResult | None,
    observed: tuple[RackOnInterval, ...] | None,
    observed_racks: tuple[ComputeRack, ...] | None,
) -> Amount:
    if integrated is not None:
        if observed is not None or observed_racks is not None:
            raise ValueError("choose one rack activity source")
        return Amount(fsum(item.on_seconds for item in integrated.racks) / 3600)
    if observed is not None:
        racks = (
            observed_racks
            if observed_racks is not None
            else tuple(
                {
                    (item.rack.site_identifier, item.rack.identifier): item.rack
                    for item in observed
                }.values()
            )
        )
        if len(racks) != result.rack_count:
            return Amount.missing("observed rack intervals do not identify all scenario racks")
        if simulate_rack_intervals(result.scenario, racks, observed) != result:
            raise ValueError("observed rack intervals do not match thermal result")
        spans: dict[tuple[str, str], list] = {}
        for item in observed:
            spans.setdefault((item.rack.site_identifier, item.rack.identifier), []).append(
                (item.start, item.end)
            )
        return Amount(fsum(union_seconds(value) for value in spans.values()) / 3600)
    if observed_racks is not None:
        raise ValueError("observed rack inventory requires intervals")
    if simulate_scenario(result.scenario) != result:
        return Amount.missing("rack activity source required for compute-driven result")
    return Amount(
        fsum(
            site.quantity * rack.quantity * point.interval.duration_hours
            for site in result.scenario.sites
            for rack in site.racks
            for point in rack.operation
            if point.on
        )
    )


def _difference(label: str, positive: tuple[Amount, ...], negative: tuple[Amount, ...]) -> Amount:
    combined = _combine(label, *positive, *negative)
    if combined.value is None:
        return combined
    return Amount(fsum(x.value for x in positive) - fsum(x.value for x in negative))


def evaluate(
    source: ScenarioResult | IntegratedResult,
    inputs: Economics,
    *,
    observed_intervals: tuple[RackOnInterval, ...] | None = None,
    observed_racks: tuple[ComputeRack, ...] | None = None,
) -> EconomicResult:
    """Calculate period results; annualize only a complete Zurich calendar year."""
    integrated = source if isinstance(source, IntegratedResult) else None
    result = integrated.thermal if integrated is not None else source
    annual = _annual(result)
    prices = {price.site_identifier: price for price in inputs.site_prices}
    if len(prices) != len(inputs.site_prices):
        raise ValueError("duplicate site prices")
    if set(prices) - {site.identifier for site in result.scenario.sites}:
        raise ValueError("prices reference unknown site")
    electricity_values, heat_values, backup_values, useful_values = [], [], [], []
    electricity_missing, heat_missing, backup_missing, useful_missing = [], [], [], []
    intervals = tuple(point.interval for point in result.scenario.sites[0].demand.points)
    for site_result in result.sites:
        site = site_result.site
        price = prices.get(site.identifier)
        electrical = _rates(price.electricity if price else None, intervals, "electricity")
        heat = _rates(price.heat if price else None, intervals, "heat")
        backup = _rates(price.backup if price else None, intervals, "backup")
        uncertain = (
            site.initial_storage_kwh > 0
            and not (price and price.opening_storage_is_server_heat)
            and any(flow.storage_discharge_kwh > 0 for flow in site_result.per_site_flows)
        )
        if uncertain:
            useful_missing.append(f"{site.identifier} opening storage origin unknown")
        if electrical is None:
            electricity_missing.append(f"{site.identifier} electricity tariff missing")
        if heat is None:
            heat_missing.append(f"{site.identifier} heat value missing")
        if backup is None:
            backup_missing.append(f"{site.identifier} backup heat price missing")
        for index, flow in enumerate(site_result.per_site_flows):
            quantity = site.quantity
            useful = flow.direct_supply_kwh + flow.storage_discharge_kwh
            useful_values.append(useful * quantity)
            if electrical is not None:
                electricity_values.append(flow.electrical_energy_kwh * electrical[index] * quantity)
            if heat is not None:
                heat_values.append(useful * heat[index] * quantity)
            if backup is not None:
                backup_values.append(flow.backup_heat_kwh * backup[index] * quantity)

    def amount(values: list[float], errors: list[str]) -> Amount:
        return Amount.missing("; ".join(errors)) if errors else Amount(fsum(values))

    electricity_cost = amount(electricity_values, electricity_missing)
    useful_heat = amount(useful_values, useful_missing)
    heat_value = amount(heat_values, heat_missing + useful_missing)
    backup_cost = amount(backup_values, backup_missing)
    modes = {price.heat_mode for price in prices.values()}
    if len(modes) > 1:
        raise ValueError("mixed heat economic perspectives are not supported")
    mode = next(iter(modes), "avoided")
    avoided = heat_value if mode == "avoided" else Amount(0)
    revenue = heat_value if mode == "revenue" else Amount(0)
    hardware = _cost(inputs.hardware, result, "hardware")
    installation = _cost(inputs.installation, result, "installation")
    capex = _combine("CAPEX", hardware, installation)
    service = _cost(inputs.service, result, "service", annual=True)
    other = _cost(inputs.other_annual_opex, result, "other OPEX", annual=True)
    if not annual:
        service = Amount.missing("service cost requires full calendar year")
        other = Amount.missing("other annual OPEX requires full calendar year")
    if capex.value is None or inputs.lifetime_years is None or inputs.discount_rate is None:
        reasons = []
        if capex.value is None:
            reasons.append(capex.reason)
        if inputs.lifetime_years is None:
            reasons.append("lifetime missing")
        if inputs.discount_rate is None:
            reasons.append("discount rate missing")
        annualized = Amount.missing("; ".join(str(x) for x in reasons))
    else:
        lifetime = _number(inputs.lifetime_years, "year")
        rate = _number(inputs.discount_rate, "dimensionless")
        if lifetime <= 0:
            raise ValueError("lifetime must be positive")
        annualized = Amount(
            capex.value / lifetime
            if rate == 0
            else capex.value * rate / -expm1(-lifetime * log1p(rate))
        )
    rack_hours = _rack_hours(result, integrated, observed_intervals, observed_racks)
    if inputs.sold_server_hours is None:
        sold = Amount.missing("sold server-hours missing")
    else:
        sold_value = _number(inputs.sold_server_hours, "server-hour")
        if rack_hours.value is None:
            sold = Amount.missing("cannot validate sold hours: " + str(rack_hours.reason))
        elif sold_value > rack_hours.value + 1e-9:
            raise ValueError("sold server-hours exceed physical rack ON hours")
        else:
            sold = Amount(sold_value, classification="configured")
    income_missing = []
    if inputs.compute_price is None:
        income_missing.append("compute sale price missing")
    if sold.value is None:
        income_missing.append(str(sold.reason))
    if income_missing:
        income = Amount.missing("; ".join(income_missing))
    else:
        income = Amount(sold.value * _number(inputs.compute_price, "CHF/server-hour"))
    opex = _combine("OPEX", electricity_cost, service, other, backup_cost)
    # Absolute site perspective: backup already reflects server heat; don't subtract avoided cost.
    net = _difference("net cash contribution", (income, revenue), (opex,))
    total = _difference("annualized total cost", (annualized, opex), (income, revenue))
    case_numerator = _difference("case break-even", (electricity_cost,), (heat_value,))
    if mode == "avoided":
        # Incremental cost relative to the no-server heating baseline.
        full_numerator = _difference(
            "full-cost break-even", (annualized, electricity_cost, service, other), (avoided,)
        )
    else:
        # Absolute site costs include residual backup; revenue is counted once.
        full_numerator = _difference(
            "full-cost break-even",
            (annualized, electricity_cost, service, other, backup_cost),
            (revenue,),
        )

    def per_hour(numerator: Amount) -> Amount:
        if numerator.value is None and sold.value is None:
            return Amount.missing(f"{numerator.reason}; {sold.reason}")
        if numerator.value is None:
            return numerator
        if sold.value is None:
            return Amount.missing(str(sold.reason))
        if sold.value == 0:
            return Amount.missing("sold server-hours are zero")
        return Amount(numerator.value / sold.value)

    return EconomicResult(
        annual,
        "estimated" if observed_intervals is not None else "simulated",
        rack_hours,
        sold,
        useful_heat,
        fsum(row.flows.dumped_heat_kwh for row in result.intervals),
        fsum(row.flows.backup_heat_kwh for row in result.intervals),
        hardware,
        installation,
        capex,
        annualized,
        electricity_cost,
        service,
        other,
        backup_cost,
        heat_value,
        avoided,
        revenue,
        opex,
        income,
        net,
        total,
        per_hour(case_numerator),
        per_hour(full_numerator),
        inputs,
    )
