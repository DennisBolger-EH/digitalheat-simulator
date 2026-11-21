"""Run the single-rack weather demonstration on Windows."""

import argparse
import json
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from digitalheat_simulator.domain.compute import ComputeRack
from digitalheat_simulator.domain.parameters import Provenance
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
from digitalheat_simulator.simulation.compute_thermal import RackOnInterval, simulate_rack_intervals
from digitalheat_simulator.workload.live_scheduler import LiveCoordinator
from digitalheat_simulator.workload.real_worker import WeatherWorker


def run(
    weather: Path,
    root: Path,
    replicates: int,
    pre_pause: float,
    paused_seconds: float,
    on_created: Callable[[Path], None] | None = None,
) -> Path:
    if pre_pause <= 0 or paused_seconds <= 0:
        raise ValueError("demonstration durations must be positive")
    worker = WeatherWorker(
        root,
        weather,
        block_size=24,
        replicates=replicates,
        seed=19,
        electrical_kw=1.0,
        gross_kw=1.0,
        efficiency=0.8,
    )
    if on_created is not None:
        on_created(worker.journal)
    thermal = Rack(1.0, 1.0, 0.8)
    rack = ComputeRack("reference-rack", "weather-site", thermal, 1, 1)
    start_clock = time.monotonic()

    def instant() -> datetime:
        return worker._anchor_utc + timedelta(
            microseconds=(time.monotonic_ns() - worker._anchor_ns) / 1000
        )

    deadline = instant() + timedelta(minutes=10)
    coordinator = LiveCoordinator(worker, rack, deadline)
    try:
        first = instant()
        coordinator.evaluate(
            now=first, interval_end=deadline, opportunity_kwh=1, estimated_remaining_seconds=120
        )
        time.sleep(pre_pause)
        observed = worker.command("status")
        if observed["progress"] <= 0:
            raise RuntimeError("no worker progress before pause")
        estimate = max(
            0.001,
            observed["active_ns"]
            / 1e9
            * (replicates - observed["progress"])
            / observed["progress"],
        )
        low_signal = instant()
        if (
            coordinator.evaluate(
                now=low_signal,
                interval_end=deadline,
                opportunity_kwh=0,
                estimated_remaining_seconds=estimate,
            )
            is not None
        ):
            raise RuntimeError("scheduler did not request pause")
        pause = worker.command("status")
        time.sleep(paused_seconds)
        paused_status = worker.command("status")
        if (pause["progress"], pause["active_ns"]) != (
            paused_status["progress"],
            paused_status["active_ns"],
        ):
            raise RuntimeError("worker progressed while paused")
        worker.command("checkpoint")
        high_signal = instant()
        if (
            coordinator.evaluate(
                now=high_signal,
                interval_end=deadline,
                opportunity_kwh=1,
                estimated_remaining_seconds=estimate,
            )
            is None
        ):
            raise RuntimeError("scheduler did not request resume")
        worker.complete(timeout=600)
        elapsed = time.monotonic() - start_clock
        worker.cleanup()
        end = instant() + timedelta(seconds=1)
        intervals = (
            Interval(first - timedelta(seconds=1), low_signal),
            Interval(low_signal, high_signal),
            Interval(high_signal, end),
        )
        source = Provenance("synthetic demonstrator heat signal", unit="kWh")
        demand = ThermalDemandSeries(
            "weather-site",
            tuple(
                DemandPoint(interval, value)
                for interval, value in zip(intervals, (1, 0, 1), strict=True)
            ),
            source,
        )
        other_demand = ThermalDemandSeries(
            "other-site", tuple(DemandPoint(interval, 1) for interval in intervals), source
        )
        group = RackGroup("rack", thermal, 1, tuple(OperationPoint(i, False) for i in intervals))
        scenario = Scenario(
            (
                SiteGroup("weather-site", "synthetic", 1, demand, (group,), 0, 0),
                SiteGroup("other-site", "synthetic", 1, other_demand, (), 0, 0),
            )
        )
        spans = tuple(
            RackOnInterval(
                rack,
                datetime.fromisoformat(item["start_utc"]),
                datetime.fromisoformat(item["end_utc"]),
            )
            for item in worker.data["intervals"]
        )
        result = simulate_rack_intervals(scenario, (rack,), spans)
        worker.data["thermal"] = {
            "demand_source": "synthetic: 1, 0, 1 kWh for weather site; 1 kWh per interval at other site",
            "site_results": {
                site.site.identifier: [asdict(flow) for flow in site.per_site_flows]
                for site in result.sites
            },
        }
        worker.data["demonstration"] = {
            "wall_duration_seconds_measured": elapsed,
            "progress_before_pause": observed["progress"],
            "progress_paused": pause["progress"],
            "progress_after_paused_wait": paused_status["progress"],
            "progress_complete": worker.data["progress_measured"],
            "pause_wait_seconds_configured": paused_seconds,
            "planning_estimate_initial_seconds_configured": 120,
            "planning_estimate_after_progress_seconds_derived": estimate,
            "signal_changes_utc": [low_signal.isoformat(), high_signal.isoformat()],
        }
        worker._save()
        return worker.journal
    finally:
        worker.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weather", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--replicates", type=int, default=100000)
    parser.add_argument("--pre-pause", type=float, default=3)
    parser.add_argument("--paused-seconds", type=float, default=3)
    args = parser.parse_args()
    journal = run(
        args.weather, args.output_root, args.replicates, args.pre_pause, args.paused_seconds
    )
    print(
        json.dumps(
            {"journal": str(journal), **json.loads(journal.read_text(encoding="utf-8"))}, indent=2
        )
    )


if __name__ == "__main__":
    main()
