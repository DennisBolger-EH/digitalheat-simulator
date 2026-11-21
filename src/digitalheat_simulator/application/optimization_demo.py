"""Synthetic, explicitly non-market annual optimization example."""

import json
import platform
import time
from dataclasses import asdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from digitalheat_simulator.application.optimization import ScenarioEvaluator
from digitalheat_simulator.domain.parameters import Parameter, ParameterGroup, Provenance
from digitalheat_simulator.domain.scenario import (
    DemandPoint,
    Interval,
    OperationPoint,
    RackGroup,
    Scenario,
    SiteGroup,
    ThermalDemandSeries,
)
from digitalheat_simulator.domain.thermal import Rack
from digitalheat_simulator.finance.model import Economics, SitePrices
from digitalheat_simulator.optimization.search import search


def parameter(name, value, unit, *, low=None, high=None, step=None, integer=False):
    return Parameter(
        name,
        value,
        "integer" if integer else "number",
        "scenario",
        unit,
        minimum=low,
        maximum=high,
        step=step,
        optimizable=low is not None,
        provenance=Provenance("synthetic demonstration; not a market value", unit=unit),
    )


def example():
    zone = ZoneInfo("Europe/Zurich")
    start = datetime(2025, 1, 1, tzinfo=zone)
    middle = start + timedelta(days=182)
    end = datetime(2026, 1, 1, tzinfo=zone)
    intervals = (Interval(start, middle), Interval(middle, end))
    demand = ThermalDemandSeries(
        "synthetic",
        (DemandPoint(intervals[0], 0), DemandPoint(intervals[1], 5000)),
        Provenance("synthetic demonstration demand", unit="kWh"),
    )
    rack = RackGroup("rack", Rack(1, 1, 0.8), 1, tuple(OperationPoint(i, True) for i in intervals))
    scenario = Scenario((SiteGroup("house", "house", 1, demand, (rack,), 0, 0),))
    prices = SitePrices(
        "house",
        parameter("electricity", 0.25, "CHF/kWh"),
        parameter("heat", 0.1, "CHF/kWh"),
        parameter("backup", 0.1, "CHF/kWh"),
    )
    economics = Economics(
        (prices,),
        installation=(),
        service=(),
        other_annual_opex=(),
        lifetime_years=parameter("life", 10, "year"),
        discount_rate=parameter("rate", 0, "dimensionless"),
        sold_server_hours=parameter("sold", 100, "server-hour"),
    )
    groups = (
        ParameterGroup(
            "quantities",
            (parameter("rack_count:house:rack", 1, "count", low=1, high=5, step=1, integer=True),),
        ),
        ParameterGroup(
            "storage", (parameter("capacity_kwh:house", 0, "kWh", low=0, high=4, step=1),)
        ),
        ParameterGroup(
            "hardware_costs", (parameter("per_rack", 100, "CHF/rack", low=100, high=500, step=100),)
        ),
        ParameterGroup(
            "compute_income",
            (parameter("price_per_server_hour", 0, "CHF/server-hour", low=0, high=4, step=1),),
        ),
    )
    return scenario, economics, groups


def main():
    scenario, economics, groups = example()
    print(
        json.dumps(
            {
                "environment": platform.platform(),
                "python": platform.python_version(),
                "scenario": "synthetic full 2025 Zurich year, two intervals, one house, 1-5 always-on racks; no M3 jobs",
            },
            indent=2,
        )
    )
    for selected in (groups[:3], groups):
        evaluator = ScenarioEvaluator(
            scenario, economics, assumptions=("All example inputs are synthetic.",)
        )
        # When compute price is fixed, retain its explicit synthetic value.
        used = (
            selected
            if len(selected) == 4
            else selected
            + (
                ParameterGroup(
                    "compute_income", (parameter("price_per_server_hour", 0, "CHF/server-hour"),)
                ),
            )
        )
        started = time.perf_counter()
        result = search(used, evaluator, "economic", budget=625)
        elapsed = time.perf_counter() - started
        print(
            json.dumps(
                {
                    "candidates": result.evaluated_count,
                    "seconds": elapsed,
                    "candidates_per_second": result.evaluated_count / elapsed,
                    "feasible": result.feasible_count,
                    "rejected": result.rejected_count,
                    "cache_hits": evaluator.cache_hits,
                    "m3_scheduling": False,
                    "best_value_chf": result.best.objective_value if result.best else None,
                    "best_groups": [asdict(g) for g in result.best.groups] if result.best else None,
                },
                default=str,
            )
        )
    thermal = search(groups, ScenarioEvaluator(scenario, economics), "thermal", budget=625)
    print(
        json.dumps(
            {
                "thermal_best_kwh": thermal.best.objective_value,
                "feasible": thermal.feasible_count,
                "rejected": thermal.rejected_count,
                "best_groups": [asdict(g) for g in thermal.best.groups],
            },
            default=str,
        )
    )


if __name__ == "__main__":
    main()
