"""Incremental single-worker coordinator using the M3 reference admission policy."""

from datetime import datetime

from digitalheat_simulator.domain.compute import ComputeRack
from digitalheat_simulator.workload.real_worker import WeatherWorker
from digitalheat_simulator.workload.scheduler import live_single_rack_decision


class LiveCoordinator:
    def __init__(self, worker: WeatherWorker, rack: ComputeRack, deadline: datetime) -> None:
        self.worker = worker
        self.rack = rack
        self.deadline = deadline

    def evaluate(
        self,
        *,
        now: datetime,
        interval_end: datetime,
        opportunity_kwh: float,
        estimated_remaining_seconds: float,
    ) -> datetime | None:
        """Apply one observed local signal, then await each required acknowledgement."""
        decision = live_single_rack_decision(
            now=now,
            interval_end=interval_end,
            deadline=self.deadline,
            estimated_remaining_seconds=estimated_remaining_seconds,
            opportunity_kwh=opportunity_kwh,
            rack=self.rack,
        )
        self.worker._record(
            "scheduler decision",
            execution_id=self.worker.execution_id,
            observed_state=self.worker._state,
            progress_measured=self.worker.data["progress_measured"],
            opportunity_kwh=opportunity_kwh,
            estimated_remaining_seconds=estimated_remaining_seconds,
            run=decision is not None,
            permitted_until=None if decision is None else decision.isoformat(),
            signal_time=now.isoformat(),
        )
        if decision is None and self.worker._state == "running":
            self.worker.command("pause")
        elif decision is not None and self.worker._state == "created":
            self.worker.start()
            self.worker.command("resume")
        elif decision is not None and self.worker._state == "paused":
            self.worker.command("resume")
        return decision
