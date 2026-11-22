"""Interactive local demonstrator; all model calculations live in application services."""

import copy
import logging
from dataclasses import replace
from pathlib import Path

from nicegui import run, ui

from digitalheat_simulator.application.dashboard import (
    Configuration,
    reference_fields,
    run_optimization,
    run_simulation,
)
from digitalheat_simulator.application.kpi_explanations import (
    chart_explanations,
    not_calculated,
    optimization_explanations,
    simulation_explanations,
    workload_explanations,
)
from digitalheat_simulator.application.optimization_demo import example
from digitalheat_simulator.application.scenario_bundle import BundleScenario, ScenarioBundle
from digitalheat_simulator.application.workload_view import Demonstration
from digitalheat_simulator.config.bundle_csv import export_bundle, import_bundle
from digitalheat_simulator.config.scenario_csv import DEFAULTS, load_default
from digitalheat_simulator.ui.kpi_inventory import (
    COMPUTE_DETAILS,
    ECONOMIC_DETAILS,
    OPTIMIZATION_RESULTS,
    PRIMARY_CARDS,
    STORAGE_CHART_SERIES,
    THERMAL_CHART_SERIES,
    THERMAL_DETAILS,
    WORKLOAD_RESULTS,
)
from digitalheat_simulator.ui.plots import candidates_figure, storage_figure, thermal_figure

LOG = logging.getLogger(__name__)
WORKLOAD = Demonstration(Path(__file__).resolve().parents[3] / "artifacts" / "m4-ui")

STYLE = """
<style>
body { zoom: 1.3; }
.dashboard-layout { flex-wrap: wrap !important; }
.dashboard-sidebar { width: 20rem; max-width: 100%; }
.dashboard-content { flex: 1 1 25rem; min-width: 0; max-width: 100%; }
.kpi-card { flex: 1 1 12rem; min-width: 0; overflow-wrap: anywhere; }
.scenario-files { gap: .35rem; }
.scenario-files .q-btn { max-width: 100%; }
.q-tab__label, .q-btn__content { white-space: normal; }
.kpi-explanation { white-space: pre-wrap; overflow-wrap: anywhere; max-width: 32rem; }
.kpi-tooltip { white-space: pre-wrap; max-width: 26rem; max-height: 65vh; overflow-y: auto; }
</style>
"""


def _show(value, unit="", reason=None):
    if value is None:
        return f"Unavailable — {reason or 'not supplied or not applicable'}"
    if isinstance(value, float):
        return f"{value:,.3f} {unit}".strip()
    return f"{value} {unit}".strip()


def _amount(amount, unit):
    return _show(amount.value, unit, amount.reason)


def _clear_results(results, identities):
    for key in ("simulation", "optimization"):
        results[key] = None
        identities[key] = None


def page() -> None:
    scenarios = {
        "reference-house": BundleScenario("reference-house", "Reference House", Configuration()),
        "synthetic-complete-demo": BundleScenario(
            "synthetic-complete-demo", "Synthetic Complete Demo", load_default("complete")
        ),
        "synthetic-optimization-demo": BundleScenario(
            "synthetic-optimization-demo",
            "Synthetic optimization demo",
            Configuration(mode="synthetic"),
        ),
    }
    bundle = ScenarioBundle(2, "Built-in scenarios", None, scenarios, "reference-house")
    state = bundle.active.configuration
    status = {"simulation": "Ready", "optimization": "Ready", "workload": "Ready"}
    results = {"simulation": None, "optimization": None}
    result_identity = {"simulation": None, "optimization": None}
    source_labels = {}
    pending = {"bundle": None}
    last_workload = {"snapshot": None}

    def show_explanation(explanation):
        explanation_text.set_text(explanation.format())
        explanation_dialog.open()

    def explanation_affordance(explanation):
        ui.button(
            icon="info",
            on_click=lambda: show_explanation(explanation),
        ).props(f'flat round dense aria-label="Details for {explanation.title}"')

    def explained_label(text, explanation):
        with ui.row().classes("items-center gap-1"):
            ui.tooltip(explanation.format()).classes("kpi-tooltip")
            ui.label(text)
            explanation_affordance(explanation)

    def search_summary(result):
        explanations = optimization_explanations(result)
        ui.label(f"{result.method} · {result.result_label}")
        with ui.row().classes("items-center gap-1"):
            for key in OPTIMIZATION_RESULTS[1:]:
                explanation = explanations[key]
                explained_label(f"{explanation.title}: {explanation.result}", explanation)
        explained_label(
            f"Objective: {_show(explanations['optimization_objective'].result, explanations['optimization_objective'].result_unit)}",
            explanations["optimization_objective"],
        )

    def update_bundle_labels():
        active = bundle.active
        scenario_identity.set_text(f"Scenario: {active.scenario_name} ({active.scenario_id})")
        other = sum(s.dirty for s in bundle.scenarios.values() if s is not active)
        bundle_info.set_text(
            f"Loaded scenarios: {len(bundle.scenarios)} · Bundle: "
            f"{'Modified' if bundle.dirty else 'Unmodified'} · "
            f"Active: {'Modified' if active.dirty else 'Unmodified'} · Other modified: {other}"
        )
        bundle_source.set_text(f"File: {bundle.source_filename}")

    def modified():
        if state.dirty:
            ui_status.set_text("Modified — changes not yet simulated")
        update_bundle_labels()

    def change_value(key, value):
        state.set(key, value)
        if key in source_labels:
            label, unit = source_labels[key]
            label.set_text(
                f"{unit} · {'User input' if value is not None else 'Unavailable until supplied'}"
            )
        modified()
        opt_controls.refresh()

    def activate():
        explanation_dialog.close()
        _clear_results(results, result_identity)
        status["simulation"] = "Ready"
        status["optimization"] = "Ready"
        source_labels.clear()
        ui_status.set_text("Modified — changes not yet simulated" if state.dirty else "Ready")
        update_bundle_labels()
        sidebar.refresh()
        opt_controls.refresh()
        dashboard_results.refresh()
        optimization_results.refresh()

    def set_mode(value):
        nonlocal state
        if value == bundle.active_scenario_id:
            return
        if any(value == "Running" for value in status.values()):
            ui_status.set_text("Wait for the current run before switching scenarios")
            sidebar.refresh()
            return
        state = bundle.select(value).configuration
        activate()

    def export_configuration():
        try:
            text = export_bundle(bundle)
            ui.download(
                text.encode("utf-8"), filename="digitalheat-scenarios.csv", media_type="text/csv"
            )
            bundle.mark_saved()
            update_bundle_labels()
            file_feedback.set_text("Bundle download started: digitalheat-scenarios.csv")
        except ValueError as exc:
            ui_status.set_text(f"Validation error — {exc}")
            file_feedback.set_text(f"Export failed: {exc}")

    def download_template():
        try:
            contents = (DEFAULTS / "multi-scenario-template.csv").read_bytes()
            ui.download(contents, filename="multi-scenario-template.csv", media_type="text/csv")
            file_feedback.set_text("Template downloaded: multi-scenario-template.csv")
        except OSError:
            LOG.exception("Could not read scenario template")
            file_feedback.set_text("Template download failed; see server log.")

    def accept_import():
        nonlocal bundle, state
        if any(value == "Running" for value in status.values()):
            ui_status.set_text("Wait for the current run before importing")
            return
        bundle = pending["bundle"]
        pending["bundle"] = None
        state = bundle.active.configuration
        state.dirty = True
        activate()
        confirm_dialog.close()
        dialog.close()
        file_feedback.set_text(
            f"Imported {len(bundle.scenarios)} scenarios: {bundle.source_filename}"
        )
        ui_status.set_text("Modified — scenarios imported; run simulation explicitly")

    async def upload_configuration(event):
        if any(value == "Running" for value in status.values()):
            ui_status.set_text("Validation error — wait for the current run to finish")
            return
        try:
            raw = await event.file.read()
            text = raw.decode("utf-8-sig")
            filename = event.file.name.replace("\\", "/").rsplit("/", 1)[-1]
            new = await run.io_bound(import_bundle, text, filename)
            if any(value == "Running" for value in status.values()):
                raise ValueError("Wait for the current run before importing")
            pending["bundle"] = new
            if bundle.dirty:
                confirm_dialog.open()
            else:
                accept_import()
        except UnicodeDecodeError:
            ui_status.set_text("Validation error — scenario CSV must use UTF-8 encoding")
            import_message.set_text("Import failed: scenario CSV must use UTF-8 encoding.")
        except ValueError as exc:
            ui_status.set_text(f"Validation error — {exc}")
            import_message.set_text(f"Import failed. No scenarios were changed. {exc}")
        except Exception:
            LOG.exception("Scenario import failed")
            ui_status.set_text("Failed — scenario import; see server log")
            import_message.set_text("Import failed. See the server log for details.")

    def open_import():
        import_message.set_text("")
        dialog.open()

    async def execute(which):
        if any(value == "Running" for value in status.values()):
            return
        snapshot = copy.deepcopy(state)
        revision = state.revision
        identity = (bundle.active.scenario_id, bundle.active.scenario_name)
        status[which] = "Running"
        ui_status.set_text(f"Running {which}…")
        controls.refresh()
        try:
            fn = run_simulation if which == "simulation" else run_optimization
            output = await run.io_bound(fn, snapshot)
            results[which] = output
            result_identity[which] = identity
            explanation_dialog.close()
            status[which] = "Completed"
            if which == "simulation" and state.revision == revision:
                state.dirty = False
            ui_status.set_text(
                "Completed" if not state.dirty else "Completed — configuration modified"
            )
            update_bundle_labels()
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

    def update_range(key, position, value, default):
        current = list(state.ranges.get(key, default))
        current[position] = value
        state.ranges[key] = tuple(current)
        state.mark_dirty()
        modified()

    def options():
        if state.mode == "synthetic":
            _, _, groups = example()
            return [
                (
                    g.identifier,
                    replace(
                        state.metadata.get(f"synthetic:{g.identifier}:{p.identifier}", p),
                        identifier=p.identifier,
                    ),
                )
                for g in groups
                for p in g.parameters
            ]
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
                replace(
                    state.metadata[source],
                    identifier=name,
                )
                if source in state.metadata
                else Parameter(
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
            and (source not in state.metadata or state.metadata[source].enabled is not False)
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
        choices = {
            key: scenario.scenario_name + (" · Modified" if scenario.dirty else "")
            for key, scenario in bundle.scenarios.items()
        }
        ui.select(
            choices,
            label="Starting scenario",
            value=bundle.active_scenario_id,
            on_change=lambda e: set_mode(e.value),
        ).classes("w-full").tooltip(f"Scenario ID: {bundle.active_scenario_id}")
        if bundle.active_scenario_id == "swimming-pool":
            ui.label(
                "Pool setup: set a pool count and supply its 8,760-hour demand profile and source."
            ).classes("text-orange-8")
        if bundle.active_scenario_id == "synthetic-complete-demo":
            ui.label("Synthetic financial and compute inputs — not market data").classes(
                "text-orange-8"
            )
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
                        provenance = state.metadata.get(key, parameter).provenance
                        category = (
                            "User input"
                            if key in state.edited
                            or (provenance and "user input" in provenance.source.lower())
                            else "Synthetic"
                            if provenance and "synthetic" in provenance.source.lower()
                            else "Configured"
                        )
                        label = ui.label(f"{parameter.unit} · {category}").classes("text-caption")
                        source_labels[key] = (label, parameter.unit)
                        if provenance:
                            label.tooltip(f"Source: {provenance.source}")
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
                    provenance = state.metadata.get(item.identifier)
                    provenance = provenance.provenance if provenance else item.provenance
                    source = (
                        "Unavailable until supplied"
                        if state.values[item.identifier] is None
                        else "Disabled (edit to enable)"
                        if item.identifier in state.metadata
                        and state.metadata[item.identifier].enabled is False
                        else "User input"
                        if item.identifier in state.edited
                        or (provenance and "user input" in provenance.source.lower())
                        else (
                            "Synthetic"
                            if provenance and "synthetic" in provenance.source.lower()
                            else "Sourced"
                            if provenance
                            and provenance == item.provenance
                            and state.values[item.identifier] == item.value
                            and "ElCom" in provenance.source
                            else "Calculated"
                            if provenance and provenance.transformation
                            else "Configured"
                            if provenance
                            else "User input (default)"
                            if state.values.get(item.identifier) is not None
                            else "Unavailable until supplied"
                        )
                    )
                    label = ui.label(f"{item.unit} · {source}").classes("text-caption text-grey-7")
                    source_labels[item.identifier] = (label, item.unit)
                    if provenance:
                        label.tooltip(
                            f"Source: {provenance.source}; {provenance.transformation or 'no transformation'}; access date: {provenance.access_date or 'unknown'}. Edits are user inputs."
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
            current = state.ranges.get(key, default)
            with ui.row().classes("items-center w-full"):
                ui.checkbox(
                    f"{group} / {p.label or p.identifier} [{p.unit}]",
                    value=current[0],
                    on_change=lambda e, k=key, d=default: update_range(k, 0, e.value, d),
                ).classes("w-72")
                for index, name in ((1, "Min"), (2, "Max"), (3, "Step")):
                    ui.number(
                        name,
                        value=current[index],
                        on_change=lambda e, k=key, i=index, d=default: update_range(
                            k, i, e.value, d
                        ),
                    ).props("dense").classes("w-24")

    @ui.refreshable
    def dashboard_results():
        result = results["simulation"]
        if result is None:
            with ui.row().classes("w-full gap-2"):
                for name, keys in PRIMARY_CARDS:
                    with ui.card().classes("kpi-card p-3"):
                        explanation = not_calculated(keys[0], name)
                        ui.tooltip(explanation.format()).classes("kpi-tooltip")
                        ui.label(name).classes("text-caption text-grey-7")
                        ui.label("Not calculated — run a simulation").classes("text-subtitle2")
                        explanation_affordance(explanation)
            return
        ui.label(
            f"Simulation results: {result_identity['simulation'][1]} "
            f"({result_identity['simulation'][0]})"
        ).classes("text-caption")
        metrics = result.evaluation.metrics
        explanations = simulation_explanations(result)
        with ui.row().classes("w-full gap-2"):
            for name, keys in PRIMARY_CARDS:
                value = " / ".join(
                    _show(
                        explanations[key].result,
                        explanations[key].result_unit,
                        explanations[key].notes if explanations[key].result is None else None,
                    )
                    for key in keys
                )
                with ui.card().classes("kpi-card p-3"):
                    ui.tooltip("\n\n".join(explanations[key].format() for key in keys)).classes(
                        "kpi-tooltip"
                    )
                    ui.label(name).classes("text-caption text-grey-7")
                    ui.label(value).classes("text-subtitle2")
                    ui.label(
                        "Unavailable"
                        if value.startswith("Unavailable")
                        else "Calculated · simulated"
                    ).classes("text-caption")
                    with ui.row().classes("gap-1"):
                        for key in keys:
                            explanation_affordance(explanations[key])
        series = chart_explanations(result, explanations)

        def chart_details(keys):
            with ui.row().classes("items-center gap-1"):
                ui.label("Series explanations:").classes("text-caption")
                for key in keys:
                    if key == "chart_useful" and metrics.useful_heat_kwh is None:
                        continue
                    with ui.row().classes("items-center gap-1"):
                        ui.tooltip(series[key].format()).classes("kpi-tooltip")
                        ui.label(series[key].title.replace(" series", "")).classes("text-caption")
                        explanation_affordance(series[key])

        chart_details(THERMAL_CHART_SERIES)
        ui.plotly(thermal_figure(result)).classes("w-full")
        chart_details(STORAGE_CHART_SERIES)
        ui.plotly(storage_figure(result)).classes("w-full")
        with ui.row().classes("w-full"):
            with ui.column().classes("grow"):
                ui.label("January detail")
                chart_details(THERMAL_CHART_SERIES)
                ui.plotly(thermal_figure(result, 1)).classes("w-full")
            with ui.column().classes("grow"):
                ui.label("July detail")
                chart_details(THERMAL_CHART_SERIES)
                ui.plotly(thermal_figure(result, 7)).classes("w-full")
        with ui.expansion("Thermal details").classes("w-full"):
            for key in THERMAL_DETAILS:
                explanation = explanations[key]
                explained_label(
                    f"{explanation.title}: {_show(explanation.result, explanation.result_unit)}",
                    explanation,
                )
        with ui.expansion("Compute details").classes("w-full"):
            for key in COMPUTE_DETAILS:
                explanation = explanations[key]
                explained_label(
                    f"{explanation.title}: {_show(explanation.result, explanation.result_unit)}",
                    explanation,
                )
        with ui.expansion("Economic details").classes("w-full"):
            for key in ECONOMIC_DETAILS:
                explanation = explanations[key]
                explained_label(
                    f"{explanation.title}: {_show(explanation.result, explanation.result_unit)}",
                    explanation,
                )
        with ui.expansion("Optimization details").classes("w-full"):
            optimization = results["optimization"]
            if optimization is None:
                for key in OPTIMIZATION_RESULTS:
                    explanation = not_calculated(
                        key,
                        key.replace("optimization_", "").replace("_", " ").title(),
                        "Run optimization",
                    )
                    explained_label(f"{explanation.title}: Not calculated", explanation)
            else:
                search_summary(optimization)

    @ui.refreshable
    def optimization_results():
        result = results["optimization"]
        if result is None:
            for key in OPTIMIZATION_RESULTS:
                explanation = not_calculated(
                    key,
                    key.replace("optimization_", "").replace("_", " ").title(),
                    "Run optimization",
                )
                explained_label(f"{explanation.title}: Not calculated", explanation)
            return
        ui.label(
            f"Optimization results: {result_identity['optimization'][1]} "
            f"({result_identity['optimization'][0]})"
        ).classes("text-caption")
        search_summary(result)
        if result.best:
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
                        explained_label(
                            "Candidate series",
                            optimization_explanations(result)["optimization_candidates"],
                        )
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
        last_workload["snapshot"] = data
        explanations = workload_explanations(data)

        def display(key):
            explanation = explanations[key]
            value = (
                "Not calculated"
                if explanation.classification == "Not calculated"
                else _show(explanation.result, explanation.result_unit)
            )
            explained_label(f"{explanation.title}: {value}", explanation)

        ui.label("Registered workload: weather-analysis").classes("text-h6")
        ui.label("Synthetic local heat signals; configured reference rack, not host measurements.")
        ui.label(f"Worker state: {data.get('status', 'Ready')}")
        for key in WORKLOAD_RESULTS:
            display(key)
        ui.label(f"Assigned site: {'weather-site' if data.get('journal') else 'Unavailable'}")
        if data.get("notice") or data.get("uncertain"):
            ui.label(f"Uncertain: {data.get('notice') or data['uncertain']}").classes(
                "text-orange-8"
            )
        if data.get("error"):
            ui.label(str(data["error"])).classes("text-negative")
        if data.get("journal"):
            ui.label(f"Journal: {data['journal']}").classes("text-caption")

    def refresh_workload():
        if not explanation_dialog.value and WORKLOAD.snapshot() != last_workload["snapshot"]:
            workload_results.refresh()

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

    ui.add_head_html(STYLE)
    with ui.dialog() as explanation_dialog, ui.card().classes("max-h-[80vh] overflow-auto"):
        explanation_text = ui.label("").classes("kpi-explanation")
        ui.button("Close", on_click=explanation_dialog.close).props("flat")
    with ui.dialog() as confirm_dialog, ui.card():
        ui.label("The current bundle contains unsaved edits. Replace it?").classes("text-h6")
        ui.label("Export the bundle first to keep its changes.")
        with ui.row():
            ui.button("Replace bundle", on_click=accept_import)
            ui.button("Cancel", on_click=confirm_dialog.close).props("flat")
    with ui.dialog() as dialog, ui.card():
        ui.label("Import Scenarios CSV").classes("text-h6")
        ui.label("Import validates the complete file before replacing the current configuration.")
        import_message = ui.label("")
        ui.upload(
            label="Choose scenario CSV",
            auto_upload=True,
            max_file_size=2_000_000,
            on_upload=upload_configuration,
            on_rejected=lambda: import_message.set_text("Import failed: file exceeds 2 MB."),
        ).props("accept=.csv")
        ui.button("Cancel", on_click=dialog.close).props("flat")
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
        with ui.tab_panel(dash), ui.row().classes("dashboard-layout w-full items-start"):
            with ui.column().classes("dashboard-sidebar shrink-0"):
                with ui.card().classes("scenario-files w-full p-3"):
                    ui.label("Scenario Files").classes("text-h6")
                    with ui.row().classes("w-full gap-1"):
                        ui.button("Import Scenarios", on_click=open_import)
                        ui.button("Export All Scenarios", on_click=export_configuration)
                    ui.button("Download Multi-Scenario Template", on_click=download_template)
                    scenario_identity = ui.label(
                        "Scenario: Reference House (reference-house)"
                    ).classes("text-caption")
                    bundle_source = ui.label("File: Built-in scenarios").classes("text-caption")
                    bundle_info = ui.label(
                        "Loaded scenarios: 3 · Bundle: Unmodified · Active: Unmodified · Other modified: 0"
                    ).classes("text-caption")
                    file_feedback = ui.label("").classes("text-caption")
                    ui.label(
                        "Switching retains edits. The pool template needs a demand profile; "
                        "synthetic demo values are illustrative."
                    ).classes("text-caption")
                ui.label("Settings").classes("text-h6")
                sidebar()
            with ui.column().classes("dashboard-content"):
                dashboard_results()
        with ui.tab_panel(opt):
            ui.label("Optimization").classes("text-h5")
            opt_controls()
            ui.button("Find Sweet Spot", on_click=lambda: execute("optimization"))
            optimization_results()
        with ui.tab_panel(real):
            ui.button("Run registered demonstration", on_click=run_workload)
            workload_results()
            ui.timer(1.0, refresh_workload)


def main() -> None:
    ui.run(root=page, title="DigitalHeat Simulator", host="127.0.0.1", reload=False, show=False)


if __name__ in {"__main__", "__mp_main__"}:
    main()
