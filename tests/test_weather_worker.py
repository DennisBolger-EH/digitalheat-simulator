import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

WEATHER = Path("case_materials") / "open-meteo-47.56N7.55E283m.csv"


class Worker:
    def __init__(self, directory: Path, *, restore: bool = False):
        args = [
            sys.executable,
            "-m",
            "digitalheat_simulator.workload.weather_worker",
            "--weather",
            str(WEATHER.resolve()),
            "--output",
            str(directory / "result.json"),
            "--checkpoint",
            str(directory / "checkpoint.json"),
            "--block-size",
            "24",
            "--replicates",
            "1000",
            "--seed",
            "19",
        ]
        if restore:
            args.append("--restore")
        self.process = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        self.events: queue.Queue[dict] = queue.Queue()
        assert self.process.stdout is not None

        def read_events() -> None:
            assert self.process.stdout is not None
            for line in self.process.stdout:
                self.events.put(json.loads(line))

        threading.Thread(target=read_events, daemon=True).start()

    def command(self, name: str, sequence: int) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps({"command": name, "sequence": sequence}) + "\n")
        self.process.stdin.flush()

    def event(self, name: str, sequence: int | None = None) -> dict:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            event = self.events.get(timeout=max(0.01, deadline - time.monotonic()))
            if event["event"] == "error":
                raise AssertionError(event)
            if event["event"] == name and (sequence is None or event.get("sequence") == sequence):
                return event
        raise AssertionError(f"missing event {name}")

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
        self.process.communicate(timeout=10)


@pytest.mark.skipif(not WEATHER.exists(), reason="user-supplied weather CSV is not present")
def test_worker_pause_checkpoint_and_deterministic_restart(tmp_path: Path):
    worker = Worker(tmp_path)
    restored = None
    try:
        assert worker.event("ready")["progress"] == 0
        worker.command("resume", 1)
        worker.event("running", 1)
        worker.event("progress")
        worker.command("pause", 2)
        paused = worker.event("paused", 2)
        assert 0 < paused["progress"] < 1000
        time.sleep(0.1)
        worker.command("status", 3)
        status = worker.event("status", 3)
        assert status["progress"] == paused["progress"]
        assert status["active_ns"] == paused["active_ns"]
        assert status["running"] is False
        worker.command("checkpoint", 4)
        checkpoint = worker.event("checkpointed", 4)
        assert checkpoint["progress"] == paused["progress"]
        worker.command("resume", 5)
        worker.event("running", 5)
        worker.event("completed")
        assert worker.process.wait(timeout=10) == 0
        expected = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
        restored = Worker(tmp_path, restore=True)
        ready = restored.event("ready")
        assert ready["progress"] == paused["progress"]
        restored.command("resume", 1)
        restored.event("running", 1)
        assert restored.event("completed")["progress"] == 1000
        assert restored.process.wait(timeout=10) == 0
        assert json.loads((tmp_path / "result.json").read_text(encoding="utf-8")) == expected
    finally:
        worker.close()
        if restored is not None:
            restored.close()


@pytest.mark.skipif(not WEATHER.exists(), reason="user-supplied weather CSV is not present")
def test_worker_cancellation_and_corrupt_checkpoint(tmp_path: Path):
    worker = Worker(tmp_path)
    restored = None
    try:
        worker.event("ready")
        worker.command("resume", 1)
        worker.event("running", 1)
        worker.event("progress")
        worker.command("pause", 2)
        worker.event("paused", 2)
        worker.command("checkpoint", 3)
        worker.event("checkpointed", 3)
        worker.command("cancel", 4)
        worker.event("cancelled", 4)
        assert worker.process.wait(timeout=10) == 0
        assert not (tmp_path / "result.json").exists()
        checkpoint = tmp_path / "checkpoint.json"
        content = json.loads(checkpoint.read_text(encoding="utf-8"))
        content["sha256"] = "0" * 64
        checkpoint.write_text(json.dumps(content), encoding="utf-8")
        restored = Worker(tmp_path, restore=True)
        _, stderr = restored.process.communicate(timeout=10)
        assert restored.process.returncode != 0
        assert "checkpoint checksum mismatch" in stderr
    finally:
        worker.close()
        if restored is not None:
            restored.close()
