"""Interactive local demonstrator; all model calculations live in application services."""

import copy
import logging
from pathlib import Path

from nicegui import run, ui

from digitalheat_simulator.application.dashboard import (
    Configuration,
    reference_fields,
    run_optimization,
    run_simulation,
)
from digitalheat_simulator.application.optimization_demo import example
from digitalheat_simulator.application.workload_view import Demonstration
from digitalheat_simulator.ui.plots import candidates_figure, storage_figure, thermal_figure

LOG = logging.getLogger(__name__)
WORKLOAD = Demonstration(Path(__file__).resolve().parents[3] / "artifacts" / "m4-ui")


def _show(value, unit="", reason=None):
    if value is None:
        return f"Unavailable — {reason or 'not supplied or not applicable'}"
    if isinstance(value, float):
        return f"{value:,.3f} {unit}".strip()
    return f"{value} {unit}".strip()


def _amount(amount, unit):
    return _show(amount.value, unit, amount.reason)


def page() -> None:
    state = Configuration()
    status = {"simulation": "Ready", "optimization": "Ready", "workload": "Ready"}
    results = {"simulation": None, "optimization": None}
    source_labels = {}

    def modified():
        if state.dirty:
            ui_status.set_text("Modified — changes not yet simulated")

    def change_value(key, value):
        state.set(key, value)
        if key in source_labels:
            label, unit = source_labels[key]
            label.set_text(
                f"{unit} · {'User input' if value is not None else 'Unavailable until supplied'}"
            )
        modified()
        opt_controls.refresh()

    def set_mode(value):
        state.mode = value
        state.ranges.clear()
        state.mark_dirty()
        modified()
        sidebar.refresh()
        opt_controls.refresh()

    async def execute(which):
        if any(value == "Running" for value in status.values()):
            return
        snapshot = copy.deepcopy(state)
        revision = state.revision
        status[which] = "Running"
        ui_status.set_text(f"Running {which}…")
        controls.refresh()
        try:
            fn = run_simulation if which == "simulation" else run_optimization
            output = await run.io_bound(fn, snapshot)
            results[which] = output
            status[which] = "Completed"
            if which == "simulation" and state.revision == revision:
                state.dirty = False
            ui_status.set_text(
                "Completed" if not state.dirty else "Completed — configuration modified"
            )
        except ValueError as exc:
            status[which] = "Validation error"
            ui_status.set_text(f"Validation error — {exc}")
        except Exception:
            LOG.exception("%s failed", which)
            status[which] = "Failed"
            ui_status.set_text("Failed — see server log for technical details")
        controls.refresh()
        dashboard_results.refresh()
        optimization_results.refresh()

    def update_range(key, position, value):
        current = list(state.ranges.get(key, (False, None, None, None)))
        current[position] = value
        state.ranges[key] = tuple(current)
        state.mark_dirty()
        modified()

    def options():
        if state.mode == "synthetic":
            _, _, groups = example()
            return [(g.identifier, p) for g in groups for p in g.parameters]
        # Descriptors correspond to the existing M6 binding names.
        fields = {f.identifier: f for f in reference_fields()}
        descriptors = []
        for site, count, racks, storage in (
            ("house", "houses", "racks", "storage"),
            ("pool", "pools", "pool_racks", "pool_storage"),
        ):
            if not state.values.get(count):
                continue
            descriptors.extend(
                [
                    ("quantities", f"site_count:{site}", count),
                    ("quantities", f"rack_count:{site}:rack", racks),
                    ("storage", f"capacity_kwh:{site}", storage),
                    ("rack_technical", f"electrical_power_kw:{site}:rack", "electrical"),
                    ("rack_technical", f"thermal_power_kw:{site}:rack", "thermal"),
                    ("rack_technical", f"recovery_efficiency:{site}:rack", "efficiency"),
                ]
            )
            for name in ("electricity_price", "heat_value", "backup_price"):
                descriptors.append(("energy_costs", f"{name}:{site}", f"{name}:{site}"))
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
                descriptors.append((group, prefix + basis, item.identifier))
            if item.group == "Finance":
                descriptors.append(("finance_parameters", item.identifier, item.identifier))
            if item.group == "Compute income":
                descriptors.append(("compute_income", item.identifier, item.identifier))
        from digitalheat_simulator.domain.parameters import Parameter

        return [
            (
                group,
                Parameter(
                    name,
                    int(state.values[source]) if fields[source].integer else state.values[source],
                    "integer" if fields[source].integer else "number",
                    "scenario",
                    fields[source].unit,
                    label=fields[source].label,
                ),
            )
            for group, name, source in descriptors
            if state.values[source] is not None
            and (not fields[source].integer or float(state.values[source]).is_integer())
        ]

    @ui.refreshable
    def controls():
        running = any(value == "Running" for value in status.values())
        ui.button("Run Simulation", on_click=lambda: execute("simulation")).props(
            "disable" if running else ""
        )
        ui.button("Find Sweet Spot", on_click=lambda: execute("optimization")).props(
            "disable" if running else ""
        )

    @ui.refreshable
    def sidebar():
        ui.select(
            {"reference": "Reference house (sourced)", "synthetic": "Synthetic optimization demo"},
            label="Starting scenario",
            value=state.mode,
            on_change=lambda e: set_mode(e.value),
        ).classes("w-full")
        if state.mode == "synthetic":
            ui.label("Synthetic demonstration — not market data").classes("text-orange-8")
            _, _, groups = example()
            for group in groups:
                with ui.expansion(group.identifier.replace("_", " ").title(), value=True).classes(
                    "w-full"
                ):
                    for parameter in group.parameters:
                        key = f"synthetic:{group.identifier}:{parameter.identifier}"
                        ui.number(
                            parameter.identifier,
                            value=state.values.get(key, parameter.value),
                            on_change=lambda e, k=key: change_value(k, e.value),
                        ).props("dense").classes("w-full")
                        ui.label(f"{parameter.unit} · Synthetic").classes("text-caption")
            with ui.expansion("Optimization").classes("w-full"):
                objective_control()
                ui.button("Edit optimization ranges", on_click=lambda: tabs.set_value(opt)).props(
                    "flat"
                )
            return
        ui.label("2025 · Europe/Zurich · hourly").classes("text-caption")
        for group in (
            "Scenario",
            "Rack / Compute",
            "Thermal consumers",
            "Energy",
            "Hardware costs",
            "Installation costs",
            "Service / OPEX",
            "Finance",
            "Compute income",
        ):
            with ui.expansion(
                group, value=group in ("Scenario", "Rack / Compute", "Thermal consumers")
            ).classes("w-full"):
                for item in (field for field in reference_fields() if field.group == group):
                    inp = (
                        ui.number(
                            item.label,
                            value=state.values.get(item.identifier),
                            on_change=lambda e, key=item.identifier: change_value(key, e.value),
                        )
                        .props("dense clearable")
                        .classes("w-full")
                    )
                    if item.integer:
                        inp.props("step=1")
                    source = (
                        "User input"
                        if item.identifier in state.edited
                        else (
                            "Sourced"
                            if item.provenance and "ElCom" in item.provenance.source
                            else "Calculated"
                            if item.provenance and item.provenance.transformation
                            else "Configured"
                            if item.provenance
                            else "User input (default)"
                            if state.values.get(item.identifier) is not None
                            else "Unavailable until supplied"
                        )
                    )
                    label = ui.label(f"{item.unit} · {source}").classes("text-caption text-grey-7")
                    source_labels[item.identifier] = (label, item.unit)
                    if item.provenance:
                        label.tooltip(
                            f"Default source: {item.provenance.source}; {item.provenance.transformation or 'no transformation'}; access date: {item.provenance.access_date or 'unknown'}. Edits are user inputs."
                        )
                if group == "Thermal consumers":
                    ui.label(
                        "Pool: supply 8,760 hourly kWh values, one per line, aligned to the reference intervals."
                    ).classes("text-caption")

                    def set_pool(text):
                        state.pool_text = text
                        try:
                            state.pool_values = (
                                tuple(float(x.strip()) for x in text.splitlines() if x.strip())
                                if text
                                else None
                            )
                        except ValueError:
                            state.pool_values = None
                        state.mark_dirty()
                        modified()

                    ui.textarea(
                        "Pool demand profile (kWh)",
                        value=state.pool_text,
                        on_change=lambda e: set_pool(e.value or ""),
                    ).classes("w-full")

                    def set_source(value):
                        state.pool_source = value or ""
                        state.mark_dirty()
                        modified()

                    ui.input(
                        "Pool profile source",
                        value=state.pool_source,
                        on_change=lambda e: set_source(e.value),
                    ).classes("w-full")
                if group == "Energy":
                    ui.label(
                        "Reference heat-pump efficiency: 2.5 (configured case assumption). "
                        "The reference heat value is derived from 0.3325 / 2.5; "
                        "edited prices are independent user inputs."
                    ).classes("text-caption")
        with ui.expansion("Optimization").classes("w-full"):
            ui.label("Set the shared objective and ranges in the Optimization view.")
            objective_control()
            ui.button("Edit optimization ranges", on_click=lambda: tabs.set_value(opt)).props(
                "flat"
            )

    def objective_control():
        last_value = state.objective

        def change(value):
            nonlocal last_value
            if value == last_value:
                return
            last_value = value
            state.mark_dirty()
            modified()

        ui.select(
            {
                "economic": "Minimum annualized total cost",
                "thermal": "Maximum useful heat / minimum dumped heat",
            },
            label="Objective",
            on_change=lambda e: change(e.value),
        ).bind_value(state, "objective").classes("w-full")

    @ui.refreshable
    def opt_controls():
        objective_control()

        def budget_change(value):
            state.budget = int(value) if value is not None and float(value).is_integer() else value
            state.mark_dirty()
            modified()

        ui.number(
            "Candidate budget (1–625)",
            value=state.budget,
            on_change=lambda e: budget_change(e.value),
        ).props("step=1").classes("w-64")
        ui.label("Choose parameters and enter a finite grid. Other settings remain fixed.").classes(
            "text-caption"
        )
        for group, p in options():
            key = (group, p.identifier)
            default = (p.optimizable is True, p.minimum, p.maximum, p.step)
            if key not in state.ranges:
                state.ranges[key] = default
            current = state.ranges[key]
            with ui.row().classes("items-center w-full"):
                ui.checkbox(
                    f"{group} / {p.label or p.identifier} [{p.unit}]",
                    value=current[0],
                    on_change=lambda e, k=key: update_range(k, 0, e.value),
                ).classes("w-72")
                for index, name in ((1, "Min"), (2, "Max"), (3, "Step")):
                    ui.number(
                        name,
                        value=current[index],
                        on_change=lambda e, k=key, i=index: update_range(k, i, e.value),
                    ).props("dense").classes("w-24")

    @ui.refreshable
    def dashboard_results():
        result = results["simulation"]
        if result is None:
            with ui.row().classes("w-full gap-2"):
                for name in (
                    "Heat coverage",
                    "Useful server heat",
                    "Backup heat",
                    "Dumped heat",
                    "Electricity consumption",
                    "Compute utilization / work",
                    "Annualized cost",
                    "Compute income",
                ):
                    with ui.card().classes("min-w-40 grow p-3"):
                        ui.label(name).classes("text-caption text-grey-7")
                        ui.label("Unavailable — run a simulation").classes("text-subtitle2")
            return
        metrics = result.evaluation.metrics
        economics = metrics.economics
        cards = (
            (
                "Heat coverage",
                _show(
                    None if metrics.heat_coverage is None else 100 * metrics.heat_coverage,
                    "%",
                    economics.useful_heat_kwh.reason,
                ),
            ),
            ("Useful server heat", _amount(economics.useful_heat_kwh, "kWh")),
            ("Backup heat", _show(metrics.backup_heat_kwh, "kWh")),
            ("Dumped heat", _show(metrics.dumped_heat_kwh, "kWh")),
            ("Electricity consumption", _show(metrics.electricity_kwh, "kWh")),
            (
                "Compute utilization / work",
                _show(metrics.compute_utilization, "", "no scheduled compute workload")
                + " / "
                + _show(metrics.delivered_work_tflop, "TFLOP", "no scheduled compute workload"),
            ),
            ("Annualized cost", _amount(economics.annualized_total_cost_chf, "CHF/year")),
            ("Compute income", _amount(economics.compute_income_chf, "CHF/year")),
        )
        with ui.row().classes("w-full gap-2"):
            for name, value in cards:
                with ui.card().classes("min-w-40 grow p-3"):
                    ui.label(name).classes("text-caption text-grey-7")
                    ui.label(value).classes("text-subtitle2")
                    ui.label(
                        "Unavailable"
                        if value.startswith("Unavailable")
                        else "Calculated · simulated"
                    ).classes("text-caption")
        ui.plotly(thermal_figure(result)).classes("w-full")
        ui.plotly(storage_figure(result)).classes("w-full")
        with ui.row().classes("w-full"):
            with ui.column().classes("grow"):
                ui.label("January detail")
                ui.plotly(thermal_figure(result, 1)).classes("w-full")
            with ui.column().classes("grow"):
                ui.label("July detail")
                ui.plotly(thermal_figure(result, 7)).classes("w-full")
        with ui.expansion("Thermal details").classes("w-full"):
            flows = [row.flows for row in result.thermal.intervals]
            for name in (
                "demand_kwh",
                "direct_supply_kwh",
                "storage_charge_kwh",
                "storage_discharge_kwh",
                "dumped_heat_kwh",
                "backup_heat_kwh",
            ):
                ui.label(
                    f"{name.replace('_', ' ').title()}: {sum(getattr(f, name) for f in flows):,.3f} kWh"
                )
            ui.label(
                f"Space heat: {_show(result.space_heat_kwh, 'kWh')}; hot water: {_show(result.hot_water_kwh, 'kWh')}"
            )
        with ui.expansion("Compute details").classes("w-full"):
            ui.label(f"Rack hours: {_amount(economics.rack_hours, 'h')}")
            ui.label(
                f"Installed capacity: {_show(result.installed_capacity_tflop_per_s, 'TFLOP/s', 'capacity not supplied')}"
            )
            ui.label(
                "Compute work and utilization: unavailable without explicit scheduled jobs and capacity."
            )
        with ui.expansion("Economic details").classes("w-full"):
            for name in (
                "capex_chf",
                "annualized_capex_chf",
                "electricity_cost_chf",
                "service_cost_chf",
                "opex_chf",
                "useful_heat_value_chf",
                "compute_income_chf",
                "case_break_even_chf_per_server_hour",
                "full_cost_break_even_chf_per_server_hour",
                "annualized_total_cost_chf",
            ):
                unit = "CHF/server-hour" if "per_server_hour" in name else "CHF"
                ui.label(
                    f"{name.replace('_', ' ').title()}: {_amount(getattr(economics, name), unit)}"
                )
        with ui.expansion("Optimization details").classes("w-full"):
            optimization = results["optimization"]
            if optimization is None:
                ui.label("Unavailable — no optimization has been run")
            else:
                ui.label(
                    f"{optimization.objective} · {optimization.method} · {optimization.result_label} · "
                    f"{optimization.evaluated_count} evaluated · {optimization.feasible_count} feasible · "
                    f"{optimization.rejected_count} rejected"
                )
                if optimization.best is not None:
                    ui.label(f"Objective: {optimization.best.objective_value}")

    @ui.refreshable
    def optimization_results():
        result = results["optimization"]
        if result is None:
            ui.label("No optimization results yet.")
            return
        ui.label(result.result_label.capitalize()).classes("text-h6")
        ui.label(
            f"{result.method} · evaluated {result.evaluated_count}/{result.grid_size} · feasible {result.feasible_count} · rejected {result.rejected_count}"
        )
        if result.best:
            ui.label(
                f"Objective: {result.best.objective_value} {'CHF/year' if result.objective == 'economic' else 'kWh (useful, dumped)'}"
            )
            for group in result.best.groups:
                with ui.expansion(group.label or group.identifier).classes("w-full"):
                    for p in group.parameters:
                        ui.label(
                            f"{p.label or p.identifier}: {p.value} {p.unit or ''} · {p.provenance.source if p.provenance else 'source unavailable'}"
                        )
            if result.variable_keys:
                selected = {"value": result.variable_keys[0]}
                holder = ui.column().classes("w-full")

                def draw():
                    holder.clear()
                    with holder:
                        ui.plotly(candidates_figure(result, selected["value"])).classes("w-full")

                ui.select(
                    {str(i): " / ".join(k) for i, k in enumerate(result.variable_keys)},
                    value="0",
                    label="Sensitivity parameter",
                    on_change=lambda e: (
                        selected.update(value=result.variable_keys[int(e.value)]),
                        draw(),
                    ),
                ).classes("w-96")
                draw()
        else:
            ui.label("No feasible candidate. Check the rejection reasons.")
        with ui.expansion("Rejection reasons").classes("w-full"):
            reasons = sorted({reason for c in result.candidates for reason in c.rejection_reasons})
            for reason in reasons:
                ui.label(reason)
            if not reasons:
                ui.label("None")

    @ui.refreshable
    def workload_results():
        data = WORKLOAD.snapshot()
        ui.label("Registered workload: weather-analysis").classes("text-h6")
        ui.label("Synthetic local heat signals; configured reference rack, not host measurements.")
        ui.label(f"Worker state: {data.get('status', 'Ready')}")
        ui.label(
            f"Progress measured (last acknowledgement): {_show(data.get('progress'), 'replicates')} / {_show(data.get('replicates'), 'replicates')}"
        )
        ui.label(
            f"Active runtime measured (last acknowledgement): {_show(data.get('active_seconds'), 's')}"
        )
        decision = data.get("decision")
        ui.label(
            f"Scheduler decision: {('run' if decision['run'] else 'pause') if decision else 'Unavailable'}"
        )
        ui.label(f"Assigned site: {'weather-site' if data.get('journal') else 'Unavailable'}")
        ui.label(
            f"Useful heat opportunity: {_show(decision.get('opportunity_kwh') if decision else None, 'kWh')}"
        )
        ui.label(f"Checkpoint: {data.get('checkpoint') or 'Unavailable'}")
        power = data.get("power", {})
        ui.label(f"Electrical power configured: {_show(power.get('electrical_kw'), 'kW')}")
        energy = data.get("energy", {})
        ui.label(
            f"Electrical energy estimated: {_show(energy.get('electrical_kwh_estimated'), 'kWh')}"
        )
        ui.label(
            f"Recoverable heat derived: {_show(energy.get('recoverable_heat_kwh_derived'), 'kWh')}"
        )
        if data.get("notice") or data.get("uncertain"):
            ui.label(f"Uncertain: {data.get('notice') or data['uncertain']}").classes(
                "text-orange-8"
            )
        if data.get("error"):
            ui.label(str(data["error"])).classes("text-negative")
        if data.get("journal"):
            ui.label(f"Journal: {data['journal']}").classes("text-caption")

    async def run_workload():
        if any(value == "Running" for value in status.values()) or WORKLOAD.status == "Running":
            return
        status["workload"] = "Running"
        ui_status.set_text("Running registered workload…")
        controls.refresh()
        try:
            await run.io_bound(WORKLOAD.run)
            status["workload"] = "Completed"
            ui_status.set_text("Completed — registered workload")
        except Exception:
            LOG.exception("Registered workload failed")
            status["workload"] = "Failed"
            ui_status.set_text("Failed — registered workload; see server log")
        finally:
            controls.refresh()
            workload_results.refresh()

    with ui.header().classes("items-center justify-between"):
        ui.label("DigitalHeat Simulator").classes("text-h6")
        with ui.row().classes("items-center"):
            ui_status = ui.label("Ready")
            controls()
    with ui.tabs().classes("w-full") as tabs:
        dash = ui.tab("Dashboard")
        opt = ui.tab("Optimization")
        real = ui.tab("Real Workload")
    with ui.tab_panels(tabs, value=dash).classes("w-full"):
        with ui.tab_panel(dash), ui.row().classes("w-full no-wrap items-start"):
            with ui.column().classes("w-80 max-w-full shrink-0"):
                ui.label("Settings").classes("text-h6")
                sidebar()
            with ui.column().classes("grow min-w-0"):
                dashboard_results()
        with ui.tab_panel(opt):
            ui.label("Optimization").classes("text-h5")
            opt_controls()
            ui.button("Find Sweet Spot", on_click=lambda: execute("optimization"))
            optimization_results()
        with ui.tab_panel(real):
            ui.button("Run registered demonstration", on_click=run_workload)
            workload_results()
            ui.timer(1.0, workload_results.refresh)


def main() -> None:
    ui.run(root=page, title="DigitalHeat Simulator", host="127.0.0.1", reload=False, show=False)


if __name__ in {"__main__", "__mp_main__"}:
    main()
