"""Reproduce the reference-house economic calculation with explicit missing inputs."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from digitalheat_simulator.data.reference_house import load_weather, reconstruct_2025
from digitalheat_simulator.domain.parameters import Parameter, Provenance
from digitalheat_simulator.domain.scenario import OperationPoint, RackGroup, Scenario, SiteGroup
from digitalheat_simulator.domain.thermal import Rack
from digitalheat_simulator.finance.model import Economics, evaluate, reference_house_prices
from digitalheat_simulator.simulation.scenario import simulate_scenario


def calculate(weather: Path, sold_hours: float | None = None):
    samples, _, _ = load_weather(weather)
    demand = reconstruct_2025(weather, (True,) * len(samples)).as_demand_series()
    rack = Rack(1, 1, 0.8)
    group = RackGroup(
        "rack", rack, 1, tuple(OperationPoint(p.interval, True) for p in demand.points)
    )
    site = SiteGroup("reference-house", "house", 1, demand, (group,), 35, 0)
    thermal = simulate_scenario(Scenario((site,)))
    sold = None
    if sold_hours is not None:
        sold = Parameter(
            "sold_hours",
            sold_hours,
            "number",
            "scenario",
            "server-hour",
            provenance=Provenance(
                "user-configured example; not an actual sale",
                unit="server-hour",
                applicability="reference scenario",
            ),
        )
    return evaluate(
        thermal, Economics((reference_house_prices(site.identifier),), sold_server_hours=sold)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("weather", type=Path)
    parser.add_argument("--example-sold-hours", type=float)
    args = parser.parse_args()
    print(json.dumps(asdict(calculate(args.weather, args.example_sold_hours)), indent=2))


if __name__ == "__main__":
    main()
