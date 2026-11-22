"""Plotly figures from existing interval and candidate results."""

from zoneinfo import ZoneInfo

import plotly.graph_objects as go

from digitalheat_simulator.application.dashboard import DashboardResult
from digitalheat_simulator.optimization.search import SearchResult
from digitalheat_simulator.ui.kpi_inventory import (
    OPTIMIZATION_CHART_SERIES,
    STORAGE_CHART_SERIES,
    THERMAL_CHART_SERIES,
)

ZONE = ZoneInfo("Europe/Zurich")


def thermal_figure(result: DashboardResult, month: int | None = None) -> go.Figure:
    rows = result.thermal.intervals
    if month:
        rows = tuple(
            row
            for row in rows
            if row.interval.start.astimezone(ZONE).month == month
            and row.interval.duration_hours <= 24
        )
    x = [row.interval.start.astimezone(ZONE) for row in rows]
    figure = go.Figure()
    traces = [
        (THERMAL_CHART_SERIES[0], "Demand", [row.flows.demand_kwh for row in rows]),
        (
            THERMAL_CHART_SERIES[1],
            "Recoverable server heat",
            [row.flows.recoverable_heat_kwh for row in rows],
        ),
        (THERMAL_CHART_SERIES[3], "Backup heat", [row.flows.backup_heat_kwh for row in rows]),
        (
            THERMAL_CHART_SERIES[4],
            "Dumped server heat",
            [row.flows.dumped_heat_kwh for row in rows],
        ),
    ]
    if result.evaluation.metrics.useful_heat_kwh is not None:
        traces.insert(
            2,
            (
                THERMAL_CHART_SERIES[2],
                "Useful server heat",
                [row.flows.direct_supply_kwh + row.flows.storage_discharge_kwh for row in rows],
            ),
        )
    for identifier, name, values in traces:
        figure.add_scatter(
            x=x,
            y=values,
            name=name,
            meta=identifier,
            mode="lines",
            hovertemplate="%{x}<br>%{y:.3f} kWh<extra>%{fullData.name}</extra>",
        )
    figure.update_layout(
        title="Thermal energy per interval",
        yaxis_title="kWh per interval",
        xaxis_title="Europe/Zurich",
        height=330,
        margin={"l": 60, "r": 20, "t": 45, "b": 50},
    )
    return figure


def storage_figure(result: DashboardResult) -> go.Figure:
    rows = result.thermal.intervals
    figure = go.Figure()
    figure.add_scatter(
        x=[row.interval.end.astimezone(ZONE) for row in rows],
        y=[row.flows.storage_closing_kwh for row in rows],
        name="Closing storage",
        meta=STORAGE_CHART_SERIES[0],
        mode="lines",
        hovertemplate="%{x}<br>%{y:.3f} kWh<extra>%{fullData.name}</extra>",
    )
    figure.update_layout(
        title="Total site-local storage",
        yaxis_title="kWh",
        xaxis_title="Europe/Zurich",
        height=300,
        margin={"l": 60, "r": 20, "t": 45, "b": 50},
    )
    return figure


def candidates_figure(result: SearchResult, key: tuple[str, str] | None = None) -> go.Figure:
    figure = go.Figure()
    key = key or (result.variable_keys[0] if result.variable_keys else None)
    points = []
    for candidate in result.candidates:
        if not candidate.feasible or candidate.objective_value is None:
            continue
        lookup = {
            (g.identifier, p.identifier): p.value for g in candidate.groups for p in g.parameters
        }
        x = lookup.get(key) if key else len(points) + 1
        y = (
            candidate.objective_value[0]
            if isinstance(candidate.objective_value, tuple)
            else candidate.objective_value
        )
        extra = "<br>".join(
            f"{g.identifier} / {p.identifier}: {p.value} {p.unit or ''}"
            for g in candidate.groups
            for p in g.parameters
        )
        if isinstance(candidate.objective_value, tuple):
            extra += f"<br>Dumped: {candidate.objective_value[1]:.3f} kWh"
        points.append((x, y, extra))
    figure.add_scatter(
        x=[p[0] for p in points],
        y=[p[1] for p in points],
        text=[p[2] for p in points],
        mode="markers",
        name="Feasible candidates",
        meta=OPTIMIZATION_CHART_SERIES[0],
        hovertemplate="%{text}<br>Objective: %{y:.3f}<extra></extra>",
    )
    figure.update_layout(
        title="Evaluated candidates",
        xaxis_title=" / ".join(key) if key else "Candidate",
        yaxis_title="Annualized cost [CHF/year]"
        if result.objective == "economic"
        else "Useful heat [kWh]",
        height=350,
        margin={"l": 60, "r": 20, "t": 45, "b": 50},
    )
    return figure
