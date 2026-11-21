"""Narrow, process-local access to the registered M4 demonstration."""

import threading
from pathlib import Path

from digitalheat_simulator.application import real_demo
from digitalheat_simulator.application.dashboard import WEATHER
from digitalheat_simulator.workload.real_worker import read_journal, reference_energy


class Demonstration:
    def __init__(self, root: Path):
        self.root = root
        self.journal: Path | None = None
        self.status = "Ready"
        self.error: str | None = None
        self._lock = threading.Lock()

    def run(self) -> None:
        if not self._lock.acquire(blocking=False):
            raise ValueError("The registered demonstration is already running")
        try:
            self.status = "Running"
            self.error = None
            self.journal = None
            real_demo.run(WEATHER, self.root, 200000, 3, 3, self._created)
            self.status = "Completed"
        except Exception:
            self.status = "Failed"
            self.error = "The workload failed. See the server log and execution journal."
            raise
        finally:
            self._lock.release()

    def _created(self, journal: Path) -> None:
        self.journal = journal

    def snapshot(self) -> dict:
        if self.journal is None:
            return {"status": self.status, "error": self.error}
        data = read_journal(self.journal)
        if self._lock.locked():
            data.pop("recovery_notice", None)
        events = data.get("events", [])
        decisions = [event for event in events if event.get("kind") == "scheduler decision"]
        assumptions = data["power_assumptions"]
        active = data.get("active_ns_measured", 0) / 1e9
        return {
            "status": data.get("status", self.status),
            "execution_status": self.status,
            "progress": data.get("progress_measured"),
            "replicates": data["identity"]["replicates"],
            "active_seconds": active,
            "decision": decisions[-1] if decisions else None,
            "checkpoint": data.get("checkpoint"),
            "power": assumptions,
            "energy": data.get("energy")
            or reference_energy(
                active,
                assumptions["electrical_kw"],
                assumptions["gross_thermal_kw"],
                assumptions["recovery_efficiency"],
            ),
            "journal": str(self.journal),
            "error": self.error or data.get("failure"),
            "uncertain": data.get("uncertain_intervals", []),
            "notice": data.get("recovery_notice"),
        }
