"""Cooperative child process for the weather-analysis workload."""

import argparse
import hashlib
import json
import math
import os
import queue
import sys
import threading
import time
from pathlib import Path

from digitalheat_simulator.workload.weather_analysis import ALGORITHM_VERSION, WeatherAnalysis


def _encoded(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _write_atomic(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("wb") as file:
            file.write(_encoded(value))
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _emit(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, allow_nan=False), flush=True)


def run_worker(
    weather: Path,
    output: Path,
    checkpoint: Path,
    block_size: int,
    replicates: int,
    seed: int,
    restore: bool,
) -> None:
    if replicates < 1:
        raise ValueError("replicates must be positive")
    analysis = WeatherAnalysis.load(weather, block_size)
    identity = {
        "version": ALGORITHM_VERSION,
        "weather_sha256": analysis.sha256,
        "block_size": block_size,
        "replicates": replicates,
        "seed": seed,
    }
    results: list[list[float]] = []
    if restore:
        envelope = json.loads(checkpoint.read_text(encoding="utf-8"))
        payload = envelope["payload"]
        if hashlib.sha256(_encoded(payload)).hexdigest() != envelope["sha256"]:
            raise ValueError("checkpoint checksum mismatch")
        if payload["identity"] != identity:
            raise ValueError("checkpoint does not match workload inputs")
        results = payload["results"]
        if not isinstance(results, list) or len(results) >= replicates:
            raise ValueError("invalid checkpoint results")
        if any(
            not isinstance(item, list)
            or len(item) != 2
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in item)
            for item in results
        ):
            raise ValueError("invalid checkpoint regression values")

    commands: queue.Queue[dict | None] = queue.Queue()

    def read_commands() -> None:
        for line in sys.stdin:
            try:
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise TypeError("command must be an object")
                commands.put(message)
            except (ValueError, TypeError) as exc:
                commands.put({"command": "invalid", "error": str(exc)})
        commands.put(None)

    threading.Thread(target=read_commands, daemon=True).start()
    running = False
    active_started = 0
    active_ns = 0

    def elapsed_ns() -> int:
        return active_ns + (time.monotonic_ns() - active_started if running else 0)

    def report(event: str, **fields: object) -> None:
        _emit(event, progress=len(results), active_ns=elapsed_ns(), **fields)

    report("ready", identity=identity, restored=restore, pid=os.getpid())
    while True:
        try:
            message = commands.get(block=not running, timeout=None if not running else 0)
        except queue.Empty:
            message = {}
        if message is None:
            report("controller_disconnected")
            return
        command = message.get("command")
        sequence = message.get("sequence")
        if command == "resume":
            if running:
                report("error", sequence=sequence, reason="already running")
                continue
            active_started = time.monotonic_ns()
            running = True
            report("running", sequence=sequence)
        elif command == "pause":
            if not running:
                report("error", sequence=sequence, reason="not running")
                continue
            active_ns += time.monotonic_ns() - active_started
            running = False
            report("paused", sequence=sequence)
        elif command == "status":
            report("status", sequence=sequence, running=running)
        elif command == "checkpoint":
            if running:
                report("error", sequence=sequence, reason="pause before checkpoint")
                continue
            payload = {"identity": identity, "results": results}
            digest = hashlib.sha256(_encoded(payload)).hexdigest()
            _write_atomic(checkpoint, {"payload": payload, "sha256": digest})
            report("checkpointed", sequence=sequence, checkpoint_sha256=digest)
        elif command == "cancel":
            if running:
                active_ns += time.monotonic_ns() - active_started
                running = False
            report("cancelled", sequence=sequence)
            return
        elif command:
            report("error", sequence=sequence, reason="unsupported command")
        if running:
            intercept, slope = analysis.replicate(seed, len(results))
            results.append([intercept, slope])
            report("progress")
            if len(results) == replicates:
                active_ns += time.monotonic_ns() - active_started
                running = False
                _write_atomic(
                    output,
                    {
                        "identity": identity,
                        "temperature_summary": analysis.summary(),
                        "regressions": results,
                    },
                )
                report("completed", output_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
                return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weather", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--block-size", type=int, required=True)
    parser.add_argument("--replicates", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()
    run_worker(
        args.weather,
        args.output,
        args.checkpoint,
        args.block_size,
        args.replicates,
        args.seed,
        args.restore,
    )


if __name__ == "__main__":
    main()
