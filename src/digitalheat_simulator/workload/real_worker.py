"""Private, contained adapter for the registered weather-analysis worker."""

import hashlib
import json
import math
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from digitalheat_simulator.workload.weather_analysis import ALGORITHM_VERSION, WeatherAnalysis
from digitalheat_simulator.workload.weather_worker import _encoded, _write_atomic
from digitalheat_simulator.workload.windows_job import WindowsJob


def _utc() -> str:
    return datetime.now(UTC).isoformat()


def read_journal(path: Path) -> dict:
    """Read persisted evidence only; never reconnect to a persisted PID."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("execution_id"), str):
        raise ValueError("invalid or unsupported execution journal")
    if data.get("status") in {"created", "ready", "paused", "running"}:
        data["recovery_notice"] = (
            "process state after the last journal entry is unknown; no PID reattachment attempted"
        )
    return data


def reference_energy(
    seconds: float, electrical_kw: float | None, gross_kw: float | None, efficiency: float | None
) -> dict:
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("seconds must be finite and nonnegative")
    for value in (electrical_kw, gross_kw, efficiency):
        if value is not None and (not math.isfinite(value) or value < 0):
            raise ValueError("power and efficiency must be finite and nonnegative")
    if efficiency is not None and efficiency > 1:
        raise ValueError("efficiency must not exceed one")
    electrical = None if electrical_kw is None else electrical_kw * seconds / 3600
    gross = None if gross_kw is None else gross_kw * seconds / 3600
    recovered = None if gross is None or efficiency is None else gross * efficiency
    return {
        "electrical_kwh_estimated": electrical,
        "gross_heat_kwh_estimated": gross,
        "recoverable_heat_kwh_derived": recovered,
    }


class WeatherWorker:
    """One weather worker with acknowledged controls and fail-closed containment."""

    def __init__(
        self,
        root: Path,
        weather: Path,
        *,
        block_size: int,
        replicates: int,
        seed: int,
        electrical_kw: float | None = None,
        gross_kw: float | None = None,
        efficiency: float | None = None,
        restore_from: Path | None = None,
    ) -> None:
        if type(block_size) is not int or block_size < 1:
            raise ValueError("block size must be a positive integer")
        if type(replicates) is not int or replicates < 1 or type(seed) is not int:
            raise ValueError("replicates must be positive and seed must be an integer")
        reference_energy(0, electrical_kw, gross_kw, efficiency)
        self.execution_id = uuid.uuid4().hex
        root = root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        self.directory = root / self.execution_id
        self.directory.mkdir()
        self.weather = weather.resolve(strict=True)
        if not self.weather.is_file():
            raise ValueError("weather path must identify a file")
        self.output = self.directory / "result.json"
        self.checkpoint = self.directory / "checkpoint.json"
        self.journal = self.directory / "journal.json"
        self.identity = {
            "version": ALGORITHM_VERSION,
            "weather_sha256": hashlib.sha256(self.weather.read_bytes()).hexdigest(),
            "block_size": block_size,
            "replicates": replicates,
            "seed": seed,
        }
        self.restore = restore_from is not None
        checkpoint_details = None
        if restore_from is not None:
            source = restore_from.resolve(strict=True)
            if not source.is_file() or source.stat().st_size > 64 * 1024 * 1024:
                raise ValueError("invalid checkpoint file")
            envelope = json.loads(source.read_text(encoding="utf-8"))
            payload = envelope["payload"]
            digest = hashlib.sha256(_encoded(payload)).hexdigest()
            results = payload.get("results")
            if (
                envelope.get("sha256") != digest
                or payload.get("identity") != self.identity
                or not isinstance(results, list)
                or len(results) >= replicates
            ):
                raise ValueError("checkpoint checksum, identity or progress is invalid")
            _write_atomic(self.checkpoint, envelope)
            checkpoint_details = {
                "filename": self.checkpoint.name,
                "sha256": digest,
                "progress": len(results),
            }
        self.data = {
            "version": 1,
            "execution_id": self.execution_id,
            "workload": "weather-analysis",
            "identity": self.identity,
            "input_filename": self.weather.name,
            "created_utc": _utc(),
            "power_assumptions": {
                "electrical_kw": electrical_kw,
                "gross_thermal_kw": gross_kw,
                "recovery_efficiency": efficiency,
                "source": "configured reference rack, not host measurement",
            },
            "events": [],
            "intervals": [],
            "progress_measured": 0,
            "active_ns_measured": 0,
            "uncertain_intervals": [],
            "status": "created",
            "tflop_calibration": "unavailable",
            "recovered_from_checkpoint": checkpoint_details,
        }
        self._save()
        self.process: subprocess.Popen | None = None
        self.job: WindowsJob | None = None
        self._launcher_contained = False
        self._events: queue.Queue = queue.Queue(maxsize=128)
        self._errors: list[str] = []
        self._sequence = 0
        self._state = "created"
        self._active_start: int | None = None
        self._active_base = 0
        self._anchor_ns = time.monotonic_ns()
        self._anchor_utc = datetime.now(UTC)

    def _save(self) -> None:
        _write_atomic(self.journal, self.data)

    def _record(self, kind: str, **fields: object) -> None:
        fields.setdefault("monotonic_ns", time.monotonic_ns())
        fields.setdefault("execution_id", self.execution_id)
        self.data["events"].append({"kind": kind, "utc": _utc(), **fields})
        self._save()

    def _stdout(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        try:
            for line in self.process.stdout:
                if len(line) > 65536:
                    raise ValueError("worker event exceeds size limit")
                event = json.loads(line)
                if event.get("event") != "progress":
                    self._events.put(event)
        except (ValueError, OSError) as exc:
            self._events.put({"event": "protocol_failure", "reason": str(exc)})
        finally:
            self._events.put({"event": "eof"})

    def _stderr(self) -> None:
        assert self.process is not None and self.process.stderr is not None
        while True:
            chunk = self.process.stderr.read(1024)
            if not chunk:
                break
            self._errors.append(chunk)
            if sum(map(len, self._errors)) > 16384:
                self._errors[:] = ["".join(self._errors)[-16384:]]

    def start(self, timeout: float = 15) -> dict:
        if self._state != "created":
            raise RuntimeError("worker already started")
        self._sequence = 1
        self._record("START requested", sequence=1, execution_id=self.execution_id)
        args = [
            sys.executable,
            "-m",
            "digitalheat_simulator.workload.weather_worker",
            "--weather",
            str(self.weather),
            "--output",
            str(self.output),
            "--checkpoint",
            str(self.checkpoint),
            "--block-size",
            str(self.identity["block_size"]),
            "--replicates",
            str(self.identity["replicates"]),
            "--seed",
            str(self.identity["seed"]),
            "--execution-id",
            self.execution_id,
        ]
        if self.restore:
            args.append("--restore")
        env = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH", "PATHEXT"}
        }
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        try:
            self.job = WindowsJob()
            self.process = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                cwd=self.directory,
                env=env,
                shell=False,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            self.job.assign(int(self.process._handle))
            self._launcher_contained = True
            self.data["process"] = {
                "pid": self.process.pid,
                "creation_utc": _utc(),
                "identity_note": "PID and creation correlation only; never reattach by PID",
                "contained_before_start": False,
            }
            self._save()
            threading.Thread(target=self._stdout, daemon=True).start()
            threading.Thread(target=self._stderr, daemon=True).start()
            try:
                waiting = self._events.get(timeout=timeout)
            except queue.Empty as exc:
                raise TimeoutError("timed out waiting for worker start gate") from exc
            if (
                waiting.get("event") != "waiting"
                or waiting.get("execution_id") != self.execution_id
                or type(waiting.get("pid")) is not int
                or waiting["pid"] <= 0
            ):
                raise RuntimeError(f"invalid worker start gate: {waiting}")
            self.data["process"]["worker_pid"] = waiting["pid"]
            self.data["process"]["worker_creation_filetime"] = self.job.contain_worker(
                waiting["pid"]
            )
            self.data["process"]["contained_before_start"] = True
            self._save()
            self.data["start_gate_monotonic_ns"] = time.monotonic_ns()
            self._write("start", 1)
            event = self._wait("ready", 1, timeout)
            expected_progress = (
                self.data["recovered_from_checkpoint"]["progress"] if self.restore else 0
            )
            if (
                event.get("identity") != self.identity
                or event.get("pid") != waiting["pid"]
                or event.get("restored") != self.restore
                or event.get("progress") != expected_progress
            ):
                raise RuntimeError(f"worker identity mismatch: {event}, pid={self.process.pid}")
            self._active_start = event["initialization_start_ns"]
            self._close_interval(event)
            self._state = "paused"
            self.data["status"] = "ready"
            self._record(
                "READY acknowledged",
                sequence=1,
                execution_id=self.execution_id,
                progress=event["progress"],
                active_ns=event["active_ns"],
            )
            return event
        except BaseException as exc:
            self.data["status"] = "failed"
            self.data["failure"] = f"start failed: {exc}"
            if self.data.get("start_gate_monotonic_ns") is not None and self._active_start is None:
                self.data["uncertain_intervals"].append(
                    {
                        "since_monotonic_ns": self.data["start_gate_monotonic_ns"],
                        "reason": "worker initialization was not acknowledged",
                    }
                )
            self._record("FAILED", detail=self.data["failure"])
            self.cleanup(timeout=1)
            raise

    def _write(self, command: str, sequence: int) -> None:
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("worker is not running")
        self.process.stdin.write(
            json.dumps(
                {"command": command, "execution_id": self.execution_id, "sequence": sequence}
            )
            + "\n"
        )
        self.process.stdin.flush()

    def _wait(self, name: str, sequence: int | None, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"timed out waiting for {name}")
            try:
                event = self._events.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError(f"timed out waiting for {name}") from exc
            kind = event.get("event")
            if kind in {"eof", "protocol_failure"}:
                raise RuntimeError(f"worker ended before {name}: {kind}: {''.join(self._errors)}")
            if event.get("execution_id") != self.execution_id:
                raise RuntimeError("worker event execution ID mismatch")
            if kind == "error":
                raise RuntimeError(f"worker rejected command: {event}")
            if kind != name or event.get("sequence") != sequence:
                raise RuntimeError(f"unexpected or stale worker acknowledgement: {event}")
            progress = event.get("progress")
            active = event.get("active_ns")
            if (
                type(progress) is not int
                or not 0 <= progress <= self.identity["replicates"]
                or type(active) is not int
                or type(event.get("monotonic_ns")) is not int
            ):
                raise RuntimeError("invalid worker measurements")
            if (
                progress < self.data["progress_measured"]
                or active < self.data["active_ns_measured"]
            ):
                raise RuntimeError("worker measurements moved backwards")
            if (
                self._state == "paused"
                and kind != "running"
                and (
                    progress != self.data["progress_measured"]
                    or active != self.data["active_ns_measured"]
                )
            ):
                raise RuntimeError("worker progressed while acknowledged paused")
            self.data["progress_measured"] = progress
            self.data["active_ns_measured"] = active
            return event

    def command(self, command: str, timeout: float = 15) -> dict:
        expected = {
            "resume": ("paused", "running"),
            "pause": ("running", "paused"),
            "checkpoint": ("paused", "checkpointed"),
            "status": (self._state, "status"),
            "cancel": (self._state, "cancelled"),
        }
        if command not in expected or self._state != expected[command][0]:
            raise ValueError("unsupported command for current worker state")
        self._sequence += 1
        sequence = self._sequence
        self._record(
            f"{command.upper()} requested", sequence=sequence, execution_id=self.execution_id
        )
        try:
            self._write(command, sequence)
            event = self._wait(expected[command][1], sequence, timeout)
        except (RuntimeError, TimeoutError, OSError) as exc:
            self.data["status"] = "failed"
            self.data["failure"] = f"{command} not acknowledged: {exc}"
            if self._active_start is not None:
                self.data["uncertain_intervals"].append(
                    {
                        "since_monotonic_ns": self._active_start,
                        "reason": "command acknowledgement missing or invalid",
                    }
                )
            self._state = "unknown"
            self._record("FAILED", detail=self.data["failure"])
            raise
        if command == "resume":
            self._active_start = event["monotonic_ns"] - (event["active_ns"] - self._active_base)
            self._state = "running"
        elif command in {"pause", "cancel"} and self._state == "running":
            self._close_interval(event)
            self._state = "paused" if command == "pause" else "cancelled"
        elif command == "cancel":
            self._state = "cancelled"
        elif command == "checkpoint":
            envelope = json.loads(self.checkpoint.read_text(encoding="utf-8"))
            digest = hashlib.sha256(_encoded(envelope["payload"])).hexdigest()
            if digest != event["checkpoint_sha256"] or digest != envelope["sha256"]:
                raise RuntimeError("checkpoint checksum mismatch")
            if envelope["payload"]["identity"] != self.identity:
                raise RuntimeError("checkpoint identity mismatch")
            self.data["checkpoint"] = {
                "filename": self.checkpoint.name,
                "sha256": digest,
                "progress": event["progress"],
            }
        self.data["status"] = self._state
        self._record(
            f"{expected[command][1].upper()} acknowledged",
            sequence=sequence,
            execution_id=self.execution_id,
            progress=event["progress"],
            monotonic_ns=event["monotonic_ns"],
            active_ns=event["active_ns"],
        )
        return event

    def _close_interval(self, event: dict) -> None:
        if self._active_start is None:
            raise RuntimeError("missing active start")
        duration = event["active_ns"] - self._active_base
        end = self._active_start + duration
        if duration < 0 or end > event["monotonic_ns"]:
            raise RuntimeError("invalid active interval")
        start_utc = self._anchor_utc + timedelta(
            microseconds=(self._active_start - self._anchor_ns) / 1000
        )
        end_utc = start_utc + timedelta(microseconds=duration / 1000)
        self.data["intervals"].append(
            {
                "start_monotonic_ns": self._active_start,
                "end_monotonic_ns": end,
                "duration_ns": duration,
                "start_utc": start_utc.isoformat(),
                "end_utc": end_utc.isoformat(),
            }
        )
        self._active_start = None
        self._active_base = event["active_ns"]

    def complete(self, timeout: float = 120) -> dict:
        if self._state != "running":
            raise RuntimeError("worker is not running")
        event = self._wait("completed", None, timeout)
        self._close_interval(event)
        assert self.process is not None
        exit_code = self.process.wait(timeout=timeout)
        raw = self.output.read_bytes()
        result = json.loads(raw)
        regressions = result.get("regressions")
        if (
            exit_code != 0
            or hashlib.sha256(raw).hexdigest() != event["output_sha256"]
            or result.get("identity") != self.identity
            or not isinstance(regressions, list)
            or len(regressions) != self.identity["replicates"]
            or event["progress"] != self.identity["replicates"]
        ):
            raise RuntimeError("worker output validation failed")
        if any(
            not isinstance(row, list)
            or len(row) != 2
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in row)
            for row in regressions
        ):
            raise RuntimeError("invalid output regression values")
        analysis = WeatherAnalysis.load(self.weather, self.identity["block_size"])
        if (
            analysis.sha256 != self.identity["weather_sha256"]
            or result.get("temperature_summary") != analysis.summary()
            or any(
                regressions[index] != list(analysis.replicate(self.identity["seed"], index))
                for index in {0, len(regressions) // 2, len(regressions) - 1}
            )
        ):
            raise RuntimeError("output sample validation failed")
        self._state = "completed"
        self.data["status"] = "completed"
        self.data["exit_code"] = exit_code
        self.data["output"] = {
            "filename": self.output.name,
            "sha256": event["output_sha256"],
            "validated": True,
        }
        assumptions = self.data["power_assumptions"]
        self.data["energy"] = reference_energy(
            event["active_ns"] / 1e9,
            assumptions["electrical_kw"],
            assumptions["gross_thermal_kw"],
            assumptions["recovery_efficiency"],
        )
        self._record(
            "COMPLETE acknowledged and output validated",
            progress=event["progress"],
            active_ns=event["active_ns"],
            monotonic_ns=event["monotonic_ns"],
            sequence=self._sequence,
        )
        return event

    def cleanup(self, timeout: float = 5) -> None:
        process = self.process
        if process is not None and process.poll() is None:
            try:
                if self._state in {"running", "paused"}:
                    self.command("cancel", timeout=timeout)
                    process.wait(timeout=timeout)
                elif self._state == "unknown":
                    self._sequence += 1
                    self._record("CANCEL requested", sequence=self._sequence)
                    self._write("cancel", self._sequence)
                    self._wait("cancelled", self._sequence, timeout)
                    process.wait(timeout=timeout)
                else:
                    raise RuntimeError("worker state cannot be cancelled cooperatively")
            except (RuntimeError, TimeoutError, OSError, subprocess.TimeoutExpired) as exc:
                if self._active_start is not None:
                    self.data["uncertain_intervals"].append(
                        {
                            "since_monotonic_ns": self._active_start,
                            "reason": "termination without an acknowledged stop",
                        }
                    )
                self.data["status"] = "failed"
                self.data["failure"] = f"forced cleanup: {exc}"
                self._record("FAILED", detail=self.data["failure"])
                if self.job is not None:
                    self.job.close()
                    self.job = None
                if not self._launcher_contained and process.poll() is None:
                    process.terminate()
                process.wait(timeout=timeout)
        if process is not None:
            self.data["exit_code"] = process.poll()
            if self.data["status"] not in {"completed", "cancelled", "failed"}:
                self.data["status"] = "failed"
                self.data["failure"] = "worker exited unexpectedly"
                if self._active_start is not None:
                    self.data["uncertain_intervals"].append(
                        {
                            "since_monotonic_ns": self._active_start,
                            "reason": "worker exited without an acknowledged stop",
                        }
                    )
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
            self._save()
        if self.job is not None:
            self.job.close()
            self.job = None
