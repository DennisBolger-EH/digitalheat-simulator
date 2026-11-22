"""Explanations constructed from the same results used by the interface."""

from dataclasses import dataclass, replace
from math import fsum

from digitalheat_simulator.domain.parameters import Parameter


@dataclass(frozen=True)
class ExplanationInput:
    name: str
    value: object
    unit: str = ""
    provenance: str = ""


@dataclass(frozen=True)
class KpiExplanation:
    identifier: str
    title: str
    description: str
    classification: str
    formula: str
    inputs: tuple[ExplanationInput, ...]
    calculation: str
    result: object
    result_unit: str
    notes: str = ""

    def format(self) -> str:
        if self.classification == "Not calculated":
            return f"{self.title}\n\n{self.description}\n\nResult\nNot calculated"

        def display(value, precision=3):
            if value is None:
                return "Unavailable"
            if isinstance(value, float):
                return f"{value:,.{precision}f}"
            return str(value)

        inputs = "\n".join(
            f"{item.name}: {_n(item.value) if isinstance(item.value, float) else display(item.value)} {item.unit}".rstrip()
            + (f" — {item.provenance}" if item.provenance else "")
            for item in self.inputs
        )
        return (
            f"{self.title}\n{self.description}\n\nFormula\n{self.formula}\n\n"
            f"Inputs\n{inputs or 'No inputs available'}\n\n"
            f"Calculation\n{self.calculation or 'Unavailable'}\n\n"
            f"Result\n{display(self.result)} {self.result_unit}\n\n"
            f"Classification: {self.classification}" + (f"\n\n{self.notes}" if self.notes else "")
        )


def _n(value):
    return "Unavailable" if value is None else f"{value:,.12g}"


def _input(name, parameter, unit):
    if parameter is None:
        return ExplanationInput(name, None, unit)
    if isinstance(parameter, Parameter):
        source = parameter.provenance
        provenance = (
            f"{source.source}; access date: {source.access_date or 'unknown'}"
            if source
            else "source unavailable"
        )
        return ExplanationInput(name, parameter.value, unit, provenance)
    if isinstance(parameter, tuple):
        sources = sorted(
            {point.rate.provenance.source for point in parameter if point.rate.provenance}
        )
        values = [point.rate.value for point in parameter]
        return ExplanationInput(
            name,
            f"{_n(min(values))} to {_n(max(values))} across {len(parameter):,} intervals"
            if values
            else "empty rate series",
            unit,
            "; ".join(sources),
        )
    raise TypeError("expected a tariff parameter or interval tariff series")


def not_calculated(identifier, title, action="Run Simulation"):
    return KpiExplanation(
        identifier,
        title,
        f"No result is available yet. {action} to calculate this value.",
        "Not calculated",
        "",
        (),
        "",
        None,
        "",
    )


def simulation_explanations(result):
    metrics = result.evaluation.metrics
    economics = metrics.economics
    flows = tuple(row.flows for row in result.thermal.intervals)
    totals = {
        key: fsum(getattr(flow, key) for flow in flows)
        for key in (
            "demand_kwh",
            "direct_supply_kwh",
            "storage_charge_kwh",
            "storage_discharge_kwh",
            "dumped_heat_kwh",
            "backup_heat_kwh",
            "electrical_energy_kwh",
            "gross_heat_kwh",
            "recoverable_heat_kwh",
        )
    }
    aggregate = (
        f"Aggregated over {len(flows):,} intervals, {result.thermal.rack_count:,} racks "
        f"and {len(result.thermal.sites)} site groups "
        f"({sum(site.site.quantity for site in result.thermal.sites):,} sites); heat stays local."
    )
    entries = {}

    def add(key, title, description, formula, inputs, value, unit, calculation="", notes=""):
        entries[key] = KpiExplanation(
            key,
            title,
            description,
            "Unavailable" if value is None else "Calculated",
            formula,
            tuple(inputs),
            calculation,
            value,
            unit,
            notes,
        )

    def inp(name, value, unit=""):
        return ExplanationInput(name, value, unit)

    useful = economics.useful_heat_kwh
    demand = totals["demand_kwh"]
    coverage = None if metrics.heat_coverage is None else metrics.heat_coverage * 100
    add(
        "heat_coverage",
        "Heat coverage",
        "Percentage of demand met by useful server heat.",
        "Useful server heat / total thermal demand × 100",
        [
            inp("Useful server heat", useful.value, "kWh"),
            inp("Total thermal demand", demand, "kWh"),
        ],
        coverage,
        "%",
        f"{_n(useful.value)} / {_n(demand)} × 100 = {_n(coverage)} %",
        useful.reason or ("Demand is zero." if not demand else aggregate),
    )
    add(
        "useful_heat",
        "Useful server heat",
        "Server heat delivered directly or from storage.",
        "Direct server heat + storage discharge",
        [
            inp("Direct server heat", totals["direct_supply_kwh"], "kWh"),
            inp("Storage discharge", totals["storage_discharge_kwh"], "kWh"),
        ],
        useful.value,
        "kWh",
        f"{_n(totals['direct_supply_kwh'])} + {_n(totals['storage_discharge_kwh'])} = {_n(useful.value)} kWh",
        useful.reason or aggregate,
    )
    flow_descriptions = {
        "demand_kwh": ("Total thermal demand", "Sum of site demand per interval."),
        "direct_supply_kwh": ("Direct server heat", "Recovered heat used immediately."),
        "storage_charge_kwh": ("Storage charge", "Recovered heat added to site-local storage."),
        "storage_discharge_kwh": ("Storage discharge", "Stored heat delivered to meet demand."),
        "dumped_heat_kwh": ("Dumped heat", "Recoverable heat not used or stored."),
        "backup_heat_kwh": ("Backup heat", "Demand not met by direct or stored server heat."),
        "electrical_energy_kwh": (
            "Electricity consumption",
            "Electrical energy used by operating racks.",
        ),
        "gross_heat_kwh": ("Gross thermal energy", "Rack thermal energy before recovery losses."),
        "recoverable_heat_kwh": ("Recoverable heat", "Gross rack heat after recovery efficiency."),
    }
    for key, (title, description) in flow_descriptions.items():
        rule = {
            "demand_kwh": "Per interval: sum of each site's supplied demand",
            "direct_supply_kwh": "Per site and interval: minimum of demand and recoverable heat",
            "storage_charge_kwh": "Per site and interval: minimum of surplus heat and available storage capacity",
            "storage_discharge_kwh": "Per site and interval: minimum of opening storage and unmet demand after direct heat",
            "backup_heat_kwh": "Per interval: demand − direct server heat − storage discharge",
            "dumped_heat_kwh": "Per interval: recoverable heat − direct server heat − storage charge",
            "recoverable_heat_kwh": "Per rack interval: gross heat × recovery efficiency",
            "gross_heat_kwh": "Per rack interval: gross thermal power × operating duration",
            "electrical_energy_kwh": "Per rack interval: electrical power × operating duration",
        }.get(key, f"Per interval: {description}")
        flow_inputs = [
            inp("Intervals", len(flows), "intervals"),
            inp("Racks", result.thermal.rack_count, "racks"),
            inp("Sites", sum(site.site.quantity for site in result.thermal.sites), "sites"),
        ]
        if key in ("electrical_energy_kwh", "gross_heat_kwh", "recoverable_heat_kwh"):
            for site in result.thermal.scenario.sites:
                for rack in site.racks:
                    prefix = f"{site.identifier} / {rack.identifier}"
                    flow_inputs.extend(
                        [
                            inp(f"{prefix} racks", rack.quantity * site.quantity, "racks"),
                            inp(
                                f"{prefix} operating time per rack",
                                fsum(
                                    point.interval.duration_hours
                                    for point in rack.operation
                                    if point.on
                                ),
                                "h",
                            ),
                            inp(
                                f"{prefix} electrical power"
                                if key == "electrical_energy_kwh"
                                else f"{prefix} gross thermal power",
                                rack.rack.electrical_power_kw
                                if key == "electrical_energy_kwh"
                                else rack.rack.thermal_power_kw,
                                "kW",
                            ),
                        ]
                    )
                    if key == "recoverable_heat_kwh":
                        flow_inputs.append(
                            inp(
                                f"{prefix} recovery efficiency",
                                rack.rack.recovery_efficiency,
                                "dimensionless",
                            )
                        )
        if key == "backup_heat_kwh":
            flow_inputs.extend(
                [
                    inp("Demand", demand, "kWh"),
                    inp("Direct server heat", totals["direct_supply_kwh"], "kWh"),
                    inp("Storage discharge", totals["storage_discharge_kwh"], "kWh"),
                ]
            )
        if key in (
            "demand_kwh",
            "direct_supply_kwh",
            "storage_charge_kwh",
            "storage_discharge_kwh",
            "dumped_heat_kwh",
        ):
            flow_inputs.extend(
                [
                    inp("Demand total", demand, "kWh"),
                    inp("Recoverable heat total", totals["recoverable_heat_kwh"], "kWh"),
                    inp("Direct server heat total", totals["direct_supply_kwh"], "kWh"),
                    inp("Storage charge total", totals["storage_charge_kwh"], "kWh"),
                    inp("Storage discharge total", totals["storage_discharge_kwh"], "kWh"),
                ]
            )
        if key == "demand_kwh":
            flow_inputs.extend(
                ExplanationInput(
                    f"{site.identifier} demand source",
                    site.demand.identifier,
                    "",
                    site.demand.provenance.source,
                )
                for site in result.thermal.scenario.sites
            )
        add(
            key,
            title,
            description,
            f"{rule}; sum across all sites and intervals",
            flow_inputs,
            totals[key],
            "kWh",
            f"Interval total = {_n(totals[key])} kWh",
            aggregate
            + (
                f" Demand {_n(demand)} − direct {_n(totals['direct_supply_kwh'])}"
                f" − discharge {_n(totals['storage_discharge_kwh'])} kWh."
                if key == "backup_heat_kwh"
                else ""
            ),
        )
    for key, title, value in (
        ("space_heat", "Space-heating demand", result.space_heat_kwh),
        ("hot_water", "Domestic-hot-water demand", result.hot_water_kwh),
    ):
        add(
            key,
            title,
            "Reference-house reconstructed demand across house sites.",
            "Sum of reconstructed house demand × number of houses",
            [
                inp("House sites", result.thermal.site_counts.get("house", 0), "houses"),
                *[
                    ExplanationInput(
                        f"{site.identifier} demand source",
                        site.demand.identifier,
                        "",
                        site.demand.provenance.source,
                    )
                    for site in result.thermal.scenario.sites
                    if site.consumer_kind == "house"
                ],
            ],
            value,
            "kWh",
            f"Aggregated demand = {_n(value)} kWh",
            "Unavailable for scenarios without the reference reconstruction."
            if value is None
            else aggregate,
        )
    closing = flows[-1].storage_closing_kwh if flows else None
    add(
        "storage_final",
        "Final storage",
        "Total local storage at the end of the last interval.",
        "Sum of closing storage across sites in the last interval",
        [],
        closing,
        "kWh",
        f"Final interval closing storage = {_n(closing)} kWh",
        aggregate,
    )
    for key, title, value, unit in (
        ("compute_utilization", "Compute utilization", metrics.compute_utilization, ""),
        ("compute_work", "Delivered compute work", metrics.delivered_work_tflop, "TFLOP"),
    ):
        add(
            key,
            title,
            "Computed only from explicit scheduled jobs.",
            "Scheduled delivered work / available capacity"
            if key == "compute_utilization"
            else "Sum of work delivered to scheduled jobs",
            [],
            value,
            unit,
            _n(value),
            "No scheduled compute workload is configured." if value is None else "",
        )
    add(
        "rack_hours",
        "Rack hours",
        "Physical rack ON time across all sites.",
        "Sum of physical rack ON interval durations",
        [],
        economics.rack_hours.value,
        "h",
        f"Total ON time = {_n(economics.rack_hours.value)} h",
        economics.rack_hours.reason or aggregate,
    )
    capacity = result.installed_capacity_tflop_per_s
    racks = result.thermal.rack_count
    add(
        "installed_capacity",
        "Installed compute capacity",
        "Configured capacity across installed racks, not delivered work.",
        "Number of racks × configured capacity per rack",
        [
            inp("Racks", racks, "racks"),
            inp(
                "Capacity per rack",
                capacity / racks if capacity is not None and racks else None,
                "TFLOP/s",
            ),
        ],
        capacity,
        "TFLOP/s",
        f"Installed capacity = {_n(capacity)} TFLOP/s",
        "Capacity per rack is unavailable when no racks are installed."
        if racks == 0
        else "Capacity per rack not supplied."
        if capacity is None
        else "",
    )

    prices = economics.inputs.site_prices
    for key, title, field, amount, flow_name, description in (
        (
            "electricity_cost",
            "Electricity cost",
            "electricity",
            economics.electricity_cost_chf,
            "electrical_energy_kwh",
            "Cost of rack electricity.",
        ),
        (
            "heat_value",
            "Useful-heat value",
            "heat",
            economics.useful_heat_value_chf,
            None,
            "Value of useful server heat.",
        ),
        (
            "backup_cost",
            "Backup-heat cost",
            "backup",
            economics.backup_cost_chf,
            "backup_heat_kwh",
            "Cost of residual backup heat.",
        ),
    ):
        operands = []
        inputs = []
        for site in result.thermal.sites:
            price = next((p for p in prices if p.site_identifier == site.site.identifier), None)
            rate = getattr(price, field) if price else None
            energy = fsum(
                (
                    getattr(flow, flow_name)
                    if flow_name
                    else flow.direct_supply_kwh + flow.storage_discharge_kwh
                )
                * site.site.quantity
                for flow in site.per_site_flows
            )
            if (
                field == "heat"
                and site.site.initial_storage_kwh > 0
                and not (price and price.opening_storage_is_server_heat)
                and any(flow.storage_discharge_kwh > 0 for flow in site.per_site_flows)
            ):
                energy = None
            inputs.extend(
                [
                    inp(f"{site.site.identifier} energy", energy, "kWh"),
                    _input(f"{site.site.identifier} tariff", rate, "CHF/kWh"),
                ]
            )
            if isinstance(rate, Parameter):
                operands.append(f"{_n(energy)} × {_n(rate.value)}")
            elif rate is not None:
                operands.append(f"{site.site.identifier}: sum of interval energy × interval tariff")
        calc = " + ".join(operands)
        add(
            key,
            title,
            description,
            "Sum of site/interval energy × applicable tariff",
            inputs,
            amount.value,
            "CHF",
            f"{calc} = {_n(amount.value)} CHF" if calc else "",
            amount.reason or "Site-local prices and quantities are applied per interval.",
        )

    def money(key, title, amount, formula, components, notes="", expression=None):
        values = [inp(name, item.value, unit) for name, item, unit in components]
        calc = (
            expression
            if expression is not None
            else "; ".join(f"{name}: {_n(item.value)} {unit}" for name, item, unit in components)
        )
        add(
            key,
            title,
            title + " for the current scenario.",
            formula,
            values,
            amount.value,
            "CHF/server-hour"
            if "break_even" in key
            else "CHF/year"
            if key in ("annualized_capex", "annualized_cost", "service", "opex")
            else "CHF",
            calc + f" → {_n(amount.value)}",
            "\n".join(filter(None, (amount.reason, notes))),
        )

    money(
        "capex",
        "CAPEX",
        economics.capex_chf,
        "Hardware CAPEX + installation CAPEX",
        [
            ("Hardware", economics.hardware_capex_chf, "CHF"),
            ("Installation", economics.installation_capex_chf, "CHF"),
        ],
        expression=f"{_n(economics.hardware_capex_chf.value)} + {_n(economics.installation_capex_chf.value)}",
    )
    for key, title, value in (
        ("hardware_capex", "Hardware CAPEX", economics.hardware_capex_chf),
        ("installation_capex", "Installation CAPEX", economics.installation_capex_chf),
        ("service", "Service cost", economics.service_cost_chf),
        ("other_opex", "Other OPEX", economics.other_opex_chf),
    ):
        lines = getattr(
            economics.inputs,
            {
                "hardware_capex": "hardware",
                "installation_capex": "installation",
                "service": "service",
                "other_opex": "other_annual_opex",
            }[key],
        )
        values = [
            _input(f"{line.basis} cost", line.price, line.price.unit) for line in (lines or ())
        ]
        counts = {
            "scenario": 1,
            "rack": result.thermal.rack_count,
            "site": sum(site.site.quantity for site in result.thermal.sites),
            "house": result.thermal.site_counts.get("house", 0),
            "pool": result.thermal.site_counts.get("pool", 0),
        }
        for line in lines or ():
            values.append(inp(f"{line.basis} quantity", counts[line.basis], line.basis))
            values.append(
                inp(
                    f"{line.basis} tier",
                    f"{line.minimum_quantity} to {line.maximum_quantity if line.maximum_quantity is not None else 'unbounded'}",
                    line.basis,
                )
            )
        terms = [
            f"{_n(line.price.value)} × {counts[line.basis]}"
            for line in lines or ()
            if counts[line.basis] >= line.minimum_quantity
            and (line.maximum_quantity is None or counts[line.basis] <= line.maximum_quantity)
        ]
        add(
            key,
            title,
            "Applicable cost components multiplied by their configured quantities.",
            "Sum of cost component × applicable quantity",
            values,
            value.value,
            "CHF/year" if key in ("service", "other_opex") else "CHF",
            (
                f"{' + '.join(terms) if terms else 'No applicable cost lines'} = {_n(value.value)}"
                if lines is not None
                else "Cost inputs are missing."
            ),
            "\n".join(
                filter(
                    None,
                    (
                        value.reason,
                        aggregate,
                        "Cost tiers apply only when their quantity bounds are met.",
                    ),
                )
            ),
        )
    entries["capex"] = replace(
        entries["capex"],
        inputs=entries["capex"].inputs
        + entries["hardware_capex"].inputs
        + entries["installation_capex"].inputs,
    )
    capex = economics.capex_chf.value
    rate = economics.inputs.discount_rate
    life = economics.inputs.lifetime_years
    ann = economics.annualized_capex_chf
    zero = rate is not None and rate.value == 0
    formula = "CAPEX / lifetime" if zero else "CAPEX × rate / (1 − (1 + rate) ^ −lifetime)"
    calc = (
        f"{_n(capex)} / {_n(life.value if life else None)}"
        if zero
        else f"{_n(capex)} × {_n(rate.value if rate else None)} / "
        f"(1 − (1 + {_n(rate.value if rate else None)}) ^ −{_n(life.value if life else None)})"
    )
    add(
        "annualized_capex",
        "Annualized CAPEX",
        "Annualized hardware and installation investment.",
        formula,
        [
            inp("CAPEX", capex, "CHF"),
            _input("Discount rate", rate, "dimensionless"),
            _input("Lifetime", life, "year"),
        ],
        ann.value,
        "CHF/year",
        f"{calc} = {_n(ann.value)} CHF/year",
        ann.reason or "",
    )
    money(
        "opex",
        "OPEX",
        economics.opex_chf,
        "Electricity + service + other OPEX + backup cost",
        [
            ("Electricity", economics.electricity_cost_chf, "CHF"),
            ("Service", economics.service_cost_chf, "CHF/year"),
            ("Other OPEX", economics.other_opex_chf, "CHF/year"),
            ("Backup", economics.backup_cost_chf, "CHF"),
        ],
        expression=(
            f"{_n(economics.electricity_cost_chf.value)} + {_n(economics.service_cost_chf.value)}"
            f" + {_n(economics.other_opex_chf.value)} + {_n(economics.backup_cost_chf.value)}"
        ),
    )
    sold = economics.sold_server_hours
    price = economics.inputs.compute_price
    income = economics.compute_income_chf
    add(
        "compute_income",
        "Compute income",
        "Income from explicitly sold server-hours.",
        "Sold server-hours × compute sale price",
        [
            inp("Sold server-hours", sold.value, "server-hour"),
            _input(
                "Configured sold server-hours", economics.inputs.sold_server_hours, "server-hour"
            ),
            _input("Sale price", price, "CHF/server-hour"),
        ],
        income.value,
        "CHF/year" if economics.annual else "CHF",
        f"{_n(sold.value)} × {_n(price.value if price else None)} = {_n(income.value)} CHF"
        + ("/year" if economics.annual else ""),
        income.reason or "Sold hours are configured, not inferred from rack ON time.",
    )
    money(
        "annualized_cost",
        "Annualized total cost",
        economics.annualized_total_cost_chf,
        "Annualized CAPEX + OPEX − compute income − heat revenue",
        [
            ("Annualized CAPEX", ann, "CHF/year"),
            ("OPEX", economics.opex_chf, "CHF/year"),
            ("Compute income", income, "CHF/year"),
            ("Heat revenue", economics.heat_revenue_chf, "CHF/year"),
        ],
        expression=(
            f"{_n(ann.value)} + {_n(economics.opex_chf.value)}"
            f" − {_n(income.value)} − {_n(economics.heat_revenue_chf.value)}"
        ),
    )
    money(
        "case_break_even",
        "Case break-even price",
        economics.case_break_even_chf_per_server_hour,
        "(Electricity cost − useful-heat value) / sold server-hours",
        [
            ("Electricity cost", economics.electricity_cost_chf, "CHF"),
            ("Useful-heat value", economics.useful_heat_value_chf, "CHF"),
            ("Sold server-hours", sold, "server-hour"),
        ],
        "CAPEX and service costs are not included in this sprintd case-specific calculation.",
        f"({_n(economics.electricity_cost_chf.value)} − {_n(economics.useful_heat_value_chf.value)}) / {_n(sold.value)}",
    )
    mode = next(iter(prices)).heat_mode if prices else "avoided"
    formula = (
        "(Annualized CAPEX + electricity + service + other OPEX − avoided heat value) / sold server-hours"
        if mode == "avoided"
        else "(Annualized CAPEX + electricity + service + other OPEX + backup − heat revenue) / sold server-hours"
    )
    money(
        "full_break_even",
        "Full-cost break-even price",
        economics.full_cost_break_even_chf_per_server_hour,
        formula,
        [
            ("Annualized CAPEX", ann, "CHF/year"),
            ("Electricity", economics.electricity_cost_chf, "CHF"),
            ("Service", economics.service_cost_chf, "CHF/year"),
            ("Other OPEX", economics.other_opex_chf, "CHF/year"),
            (
                "Backup" if mode == "revenue" else "Avoided heat",
                economics.backup_cost_chf if mode == "revenue" else economics.avoided_heat_cost_chf,
                "CHF",
            ),
            ("Heat revenue", economics.heat_revenue_chf, "CHF"),
            ("Sold hours", sold, "server-hour"),
        ],
        f"Heat perspective: {mode}.",
        (
            f"({_n(ann.value)} + {_n(economics.electricity_cost_chf.value)}"
            f" + {_n(economics.service_cost_chf.value)} + {_n(economics.other_opex_chf.value)}"
            + (
                f" + {_n(economics.backup_cost_chf.value)} − {_n(economics.heat_revenue_chf.value)}"
                if mode == "revenue"
                else f" − {_n(economics.avoided_heat_cost_chf.value)}"
            )
            + f") / {_n(sold.value)}"
        ),
    )
    return entries


def chart_explanations(result, explanations=None):
    """Explain a series once; point hover remains responsible for individual values."""
    if explanations is None:
        explanations = simulation_explanations(result)
    specs = (
        ("chart_demand", "Demand series", "demand_kwh"),
        ("chart_recoverable", "Recoverable server heat series", "recoverable_heat_kwh"),
        ("chart_useful", "Useful server heat series", "useful_heat"),
        ("chart_backup", "Backup heat series", "backup_heat_kwh"),
        ("chart_dumped", "Dumped server heat series", "dumped_heat_kwh"),
        ("chart_storage", "Closing storage series", "storage_final"),
    )
    entries = {}
    for identifier, title, key in specs:
        base = explanations[key]
        rule = base.formula
        if identifier == "chart_useful":
            rule = "Per interval: direct server heat + storage discharge; sum across intervals"
        elif identifier == "chart_storage":
            rule = "Per site and interval: opening storage + charge − discharge; sum across sites"
        entries[identifier] = replace(
            base,
            identifier=identifier,
            title=title,
            formula=rule,
            notes=(
                base.notes + "\nPoint hover shows the interval value; monthly charts show a subset."
                if identifier != "chart_storage"
                else base.notes
                + "\nPoint hover shows closing storage; the result is the last interval, not a sum over time."
            ),
        )
    return entries


def optimization_explanation(result):
    """Describe the search rather than implying it is a closed-form calculation."""
    best = result.best
    inputs = [
        ExplanationInput("Method", result.method),
        ExplanationInput("Grid size", result.grid_size, "candidates"),
        ExplanationInput("Evaluated", result.evaluated_count, "candidates"),
        ExplanationInput("Feasible", result.feasible_count, "candidates"),
        ExplanationInput("Rejected", result.rejected_count, "candidates"),
    ]
    if best:
        for group in best.groups:
            for parameter in group.parameters:
                if (group.identifier, parameter.identifier) in result.variable_keys:
                    inputs.append(
                        _input(
                            parameter.label
                            or parameter.identifier.replace("_", " ").replace(":", " / "),
                            parameter,
                            parameter.unit or "",
                        )
                    )
    objective = (
        "Minimize annualized total cost"
        if result.objective == "economic"
        else "Maximize useful heat, then minimize dumped heat"
    )
    value = best.objective_value if best else None
    return KpiExplanation(
        "optimization_objective",
        "Best objective",
        objective,
        "Calculated" if value is not None else "Unavailable",
        "Select the best feasible evaluated candidate according to the objective",
        tuple(inputs),
        f"{result.evaluated_count} candidates evaluated; {result.feasible_count} feasible",
        value,
        "CHF/year" if result.objective == "economic" else "kWh (useful, dumped)",
        f"Status: {result.result_label}. " + " ".join(result.assumptions),
    )


def optimization_candidate_explanation(result):
    explanation = optimization_explanation(result)
    return replace(
        explanation,
        identifier="optimization_candidates",
        title="Evaluated candidate series",
        description="Each point represents one feasible candidate, not an interpolation.",
        formula=(
            "Evaluate each candidate's annualized cost"
            if result.objective == "economic"
            else "Evaluate each candidate's useful heat and dumped heat"
        ),
        notes=explanation.notes
        + "\nThe horizontal axis is the selected candidate input; other inputs may vary.",
    )


def optimization_explanations(result):
    objective = optimization_explanation(result)
    entries = {objective.identifier: objective}
    for identifier, title, value, rule in (
        (
            "optimization_grid_size",
            "Grid size",
            result.grid_size,
            "Product of declared grid-axis sizes",
        ),
        (
            "optimization_evaluated",
            "Evaluated candidates",
            result.evaluated_count,
            "Count of evaluated distinct candidates",
        ),
        (
            "optimization_feasible",
            "Feasible candidates",
            result.feasible_count,
            "Count of evaluated candidates passing all constraints",
        ),
        (
            "optimization_rejected",
            "Rejected candidates",
            result.rejected_count,
            "Count of evaluated candidates failing a constraint or objective requirement",
        ),
    ):
        entries[identifier] = replace(
            objective,
            identifier=identifier,
            title=title,
            description=rule,
            formula=rule,
            calculation=f"{value} candidates",
            result=value,
            result_unit="candidates",
            classification="Calculated",
        )
    candidate = optimization_candidate_explanation(result)
    entries[candidate.identifier] = candidate
    return entries


def workload_explanations(data):
    power = data.get("power", {})
    energy = data.get("energy", {})
    seconds = data.get("active_seconds")
    electrical = power.get("electrical_kw")
    gross = power.get("gross_thermal_kw")
    efficiency = power.get("recovery_efficiency")
    values = {}
    values["workload_electricity"] = KpiExplanation(
        "workload_electricity",
        "Estimated electricity",
        "Estimated energy, not a physical meter reading.",
        "Estimated" if energy.get("electrical_kwh_estimated") is not None else "Unavailable",
        "Configured electrical power × measured active runtime / 3,600",
        (
            ExplanationInput("Electrical power", electrical, "kW", "Configured"),
            ExplanationInput("Active runtime", seconds, "s", "Measured"),
        ),
        f"{_n(electrical)} × {_n(seconds)} / 3,600 = {_n(energy.get('electrical_kwh_estimated'))} kWh",
        energy.get("electrical_kwh_estimated"),
        "kWh",
        "Power is configured; runtime is measured. Electrical energy is estimated, not physically measured.",
    )
    values["workload_heat"] = KpiExplanation(
        "workload_heat",
        "Recoverable heat (derived)",
        "Heat derived from configured power and measured runtime.",
        "Calculated" if energy.get("recoverable_heat_kwh_derived") is not None else "Unavailable",
        "Configured gross thermal power × measured active runtime / 3,600 × recovery efficiency",
        (
            ExplanationInput("Gross thermal power", gross, "kW", "Configured"),
            ExplanationInput("Active runtime", seconds, "s", "Measured"),
            ExplanationInput("Recovery efficiency", efficiency, "dimensionless", "Configured"),
        ),
        f"{_n(gross)} × {_n(seconds)} / 3,600 × {_n(efficiency)} = {_n(energy.get('recoverable_heat_kwh_derived'))} kWh",
        energy.get("recoverable_heat_kwh_derived"),
        "kWh",
        "This is derived from a reference rack assumption, not a heat meter.",
    )
    decision = data.get("decision")
    specs = (
        (
            "workload_progress",
            "Progress (measured)",
            data.get("progress"),
            "replicates",
            "Measured",
            "Completed replicate count reported by the last acknowledged worker message.",
            (
                ExplanationInput(
                    "Configured replicates", data.get("replicates"), "replicates", "Configured"
                ),
            ),
        ),
        (
            "workload_runtime",
            "Active runtime (measured)",
            seconds,
            "s",
            "Measured",
            "Worker monotonic active-time counter, converted from nanoseconds; paused time excluded.",
            (),
        ),
        (
            "workload_power",
            "Electrical power (configured)",
            electrical,
            "kW",
            "User input",
            "Configured reference-rack electrical power; not measured from the host.",
            (),
        ),
        (
            "workload_opportunity",
            "Useful heat opportunity",
            decision.get("opportunity_kwh") if decision else None,
            "kWh",
            "User input",
            "Synthetic local heat signal supplied to the scheduler; not a measured heat flow.",
            (),
        ),
        (
            "workload_decision",
            "Scheduler decision",
            ("run" if decision["run"] else "pause") if decision else None,
            "",
            "Calculated",
            "The reference scheduler uses the heat opportunity, remaining-duration estimate and deadline.",
            (
                ExplanationInput(
                    "Heat opportunity",
                    decision.get("opportunity_kwh") if decision else None,
                    "kWh",
                    "Synthetic signal",
                ),
                ExplanationInput(
                    "Estimated remaining runtime",
                    decision.get("estimated_remaining_seconds") if decision else None,
                    "s",
                    "Estimated",
                ),
            ),
        ),
        (
            "workload_checkpoint",
            "Checkpoint",
            data.get("checkpoint"),
            "",
            "Measured",
            "Checkpoint metadata recorded after the worker acknowledged it and the checksum was validated.",
            (),
        ),
        (
            "workload_gross_heat",
            "Estimated gross thermal energy",
            energy.get("gross_heat_kwh_estimated"),
            "kWh",
            "Estimated",
            "Configured gross thermal power × measured active runtime / 3,600.",
            (
                ExplanationInput("Gross thermal power", gross, "kW", "Configured"),
                ExplanationInput("Active runtime", seconds, "s", "Measured"),
            ),
        ),
    )
    for key, title, value, unit, classification, description, inputs in specs:
        values[key] = KpiExplanation(
            key,
            title,
            description,
            classification if value is not None else "Unavailable",
            description,
            inputs,
            f"{_n(gross)} × {_n(seconds)} / 3,600 = {_n(value)} kWh"
            if key == "workload_gross_heat"
            else "Recorded value"
            if value is not None
            else "",
            value,
            unit,
            "No worker acknowledgement or input is available yet." if value is None else "",
        )
    if "power" not in data:
        for key, explanation in values.items():
            values[key] = not_calculated(key, explanation.title, "Run the registered demonstration")
    return values
