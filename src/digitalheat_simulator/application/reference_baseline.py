"""Reproduce the explicitly configured M1 reference baseline."""

import argparse
import json
import math
from pathlib import Path

from digitalheat_simulator.data.reference_house import load_weather, reconstruct_2025
from digitalheat_simulator.domain.thermal import Rack
from digitalheat_simulator.simulation.thermal import simulate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("weather_csv", type=Path)
    args = parser.parse_args()
    samples, _, _ = load_weather(args.weather_csv)
    demand = reconstruct_2025(args.weather_csv, (True,) * len(samples))
    run = simulate(demand.intervals, Rack(1.0, 1.0, 0.8), 35.0, 0.0)
    for result in run.results:
        result.validate_balances()

    def total(field: str) -> float:
        return math.fsum(getattr(result, field) for result in run.results)

    report = {
        "scenario": "M1 reconstructed 2025 reference house",
        "model_version": "m1-reference-thermal-1",
        "weather_file": str(args.weather_csv),
        "weather_sha256": demand.weather_sha256,
        "weather_metadata": dict(demand.weather_metadata),
        "transformation": demand.transformation,
        "rack_operation": "always on",
        "rack_electrical_power_kw": run.rack.electrical_power_kw,
        "rack_gross_thermal_power_kw": run.rack.thermal_power_kw,
        "heat_recovery_efficiency": run.rack.recovery_efficiency,
        "initial_storage_kwh": run.initial_storage_kwh,
        "storage_capacity_kwh": run.storage_capacity_kwh,
        "intervals": len(run.results),
        "heating_days": len(demand.heating_days),
        "space_heating_kwh": math.fsum(x.interval.space_demand_kwh for x in run.results),
        "hot_water_kwh": math.fsum(x.interval.hot_water_demand_kwh for x in run.results),
        "house_demand_kwh": math.fsum(x.demand_kwh for x in run.results),
        "rack_electrical_kwh": total("electrical_energy_kwh"),
        "gross_rack_heat_kwh": total("gross_heat_kwh"),
        "recoverable_heat_kwh": total("recoverable_heat_kwh"),
        "direct_supply_kwh": total("direct_supply_kwh"),
        "storage_charge_kwh": total("storage_charge_kwh"),
        "storage_discharge_kwh": total("storage_discharge_kwh"),
        "final_storage_kwh": run.results[-1].storage_closing_kwh,
        "dumped_heat_kwh": total("dumped_heat_kwh"),
        "backup_heat_kwh": total("backup_heat_kwh"),
        "interval_invariants": "passed",
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
