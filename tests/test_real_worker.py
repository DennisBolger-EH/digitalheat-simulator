import ctypes
import json
import sys
import time
from ctypes import wintypes
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from digitalheat_simulator.application.real_demo import run
from digitalheat_simulator.domain.compute import ComputeRack
from digitalheat_simulator.domain.thermal import Rack
from digitalheat_simulator.workload.real_worker import WeatherWorker, read_journal, reference_energy
from digitalheat_simulator.workload.scheduler import live_single_rack_decision
from digitalheat_simulator.workload.weather_worker import _write_atomic

WEATHER = Path("case_materials") / "open-meteo-47.56N7.55E283m.csv"
WINDOWS = pytest.mark.skipif(sys.platform != "win32", reason="Windows job objects required")


@pytest.mark.skipif(not WEATHER.exists(), reason="user-supplied weather CSV is not present")
@WINDOWS
def test_contained_worker_pause_and_complete(tmp_path):
    worker = WeatherWorker(
        tmp_path,
        WEATHER,
        block_size=24,
        replicates=1000,
        seed=19,
        electrical_kw=1,
        gross_kw=1,
        efficiency=0.8,
    )
    try:
        worker.start()
        worker.command("resume")
        time.sleep(0.08)
        paused = worker.command("pause")
        time.sleep(0.08)
        status = worker.command("status")
        assert status["progress"] == paused["progress"] > 0
        assert status["active_ns"] == paused["active_ns"]
        worker.command("checkpoint")
        worker.command("resume")
        done = worker.complete()
        assert done["progress"] == 1000
        journal = read_journal(worker.journal)
        assert journal["process"]["contained_before_start"]
        assert journal["output"]["validated"]
        assert journal["energy"]["electrical_kwh_estimated"] == pytest.approx(
            done["active_ns"] / 1e9 / 3600
        )
    finally:
        worker.cleanup()


def test_unavailable_energy():
    assert reference_energy(10, None, None, None) == {
        "electrical_kwh_estimated": None,
        "gross_heat_kwh_estimated": None,
        "recoverable_heat_kwh_derived": None,
    }


@pytest.mark.skipif(not WEATHER.exists(), reason="user-supplied weather CSV is not present")
@WINDOWS
def test_restart_validated_checkpoint_and_corruption(tmp_path):
    kwargs = {"block_size": 24, "replicates": 4000, "seed": 19}
    original = WeatherWorker(tmp_path, WEATHER, **kwargs)
    restored = None
    try:
        original.start()
        original.command("resume")
        time.sleep(0.08)
        paused = original.command("pause")
        original.command("checkpoint")
        original.command("resume")
        original.complete()
        expected = json.loads(original.output.read_text(encoding="utf-8"))
        restored = WeatherWorker(tmp_path, WEATHER, **kwargs, restore_from=original.checkpoint)
        assert restored.start()["progress"] == paused["progress"]
        restored.command("resume")
        restored.complete()
        assert json.loads(restored.output.read_text(encoding="utf-8")) == expected
        checkpoint = json.loads(original.checkpoint.read_text(encoding="utf-8"))
        checkpoint["sha256"] = "0" * 64
        corrupt = tmp_path / "corrupt.json"
        corrupt.write_text(json.dumps(checkpoint), encoding="utf-8")
        with pytest.raises(ValueError, match="checkpoint"):
            WeatherWorker(tmp_path, WEATHER, **kwargs, restore_from=corrupt)
    finally:
        original.cleanup()
        if restored:
            restored.cleanup()


@pytest.mark.skipif(not WEATHER.exists(), reason="user-supplied weather CSV is not present")
@WINDOWS
def test_cooperative_cancel_and_forced_cleanup(tmp_path, monkeypatch):
    worker = WeatherWorker(tmp_path, WEATHER, block_size=24, replicates=100000, seed=19)
    worker.start()
    worker.command("resume")
    worker.cleanup()
    assert read_journal(worker.journal)["status"] == "cancelled"
    assert worker.process is not None and worker.process.returncode == 0
    worker = WeatherWorker(tmp_path, WEATHER, block_size=24, replicates=100000, seed=19)
    worker.start()
    worker.command("resume")
    worker_pid = worker.data["process"]["worker_pid"]

    def timeout(*args, **kwargs):
        raise TimeoutError("simulated unresponsive worker")

    monkeypatch.setattr(worker, "command", timeout)
    worker.cleanup(timeout=2)
    journal = read_journal(worker.journal)
    assert journal["status"] == "failed"
    assert "forced cleanup" in journal["failure"]
    assert journal["uncertain_intervals"]
    assert worker.process is not None and worker.process.poll() is not None
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    deadline = time.monotonic() + 5
    while True:
        handle = kernel.OpenProcess(0x1000, False, worker_pid)
        if not handle:
            assert ctypes.get_last_error() == 87
            break
        exit_code = wintypes.DWORD()
        assert kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        kernel.CloseHandle(handle)
        if exit_code.value != 259:
            break
        assert time.monotonic() < deadline
        time.sleep(0.01)


@pytest.mark.skipif(not WEATHER.exists(), reason="user-supplied weather CSV is not present")
@WINDOWS
def test_timeout_stale_ack_and_abnormal_exit(tmp_path):
    worker = WeatherWorker(tmp_path, WEATHER, block_size=24, replicates=100000, seed=19)
    try:
        worker.start()
        with pytest.raises(TimeoutError):
            worker._wait("status", 2, 0.01)
        worker._events.put(
            {
                "event": "status",
                "execution_id": worker.execution_id,
                "sequence": 1,
                "progress": 10,
                "active_ns": 10**12,
            }
        )
        before = worker.data["progress_measured"]
        with pytest.raises(RuntimeError, match="stale"):
            worker._wait("status", 2, 1)
        assert worker.data["progress_measured"] == before
        worker.command("resume")
        assert worker.job is not None and worker.process is not None
        worker.job.close()
        worker.job = None
        worker.process.wait(timeout=5)
        with pytest.raises(RuntimeError, match="ended"):
            worker._wait("completed", None, 5)
    finally:
        worker.cleanup()
    journal = read_journal(worker.journal)
    assert journal["status"] == "failed"
    assert journal["uncertain_intervals"]


@pytest.mark.skipif(not WEATHER.exists(), reason="user-supplied weather CSV is not present")
@WINDOWS
def test_command_timeout_fails_closed(tmp_path):
    worker = WeatherWorker(tmp_path, WEATHER, block_size=24, replicates=100000, seed=19)
    try:
        worker.start()
        worker.command("resume")
        with pytest.raises(TimeoutError):
            worker.command("pause", timeout=0)
    finally:
        worker.cleanup(timeout=2)
    journal = read_journal(worker.journal)
    assert journal["status"] == "failed"
    assert journal["uncertain_intervals"]
    assert any(event["kind"] == "CANCEL requested" for event in journal["events"])


@pytest.mark.skipif(not WEATHER.exists(), reason="user-supplied weather CSV is not present")
@WINDOWS
def test_containment_failure_never_authorizes_work(tmp_path, monkeypatch):
    worker = WeatherWorker(tmp_path, WEATHER, block_size=24, replicates=1000, seed=19)

    def fail_assignment(*args):
        raise OSError("job assignment denied")

    monkeypatch.setattr(
        "digitalheat_simulator.workload.windows_job.WindowsJob.assign", fail_assignment
    )
    with pytest.raises(OSError, match="assignment denied"):
        worker.start()
    journal = read_journal(worker.journal)
    assert journal["status"] == "failed"
    assert not worker.output.exists()
    assert not any(event["kind"] == "READY acknowledged" for event in journal["events"])


@pytest.mark.skipif(not WEATHER.exists(), reason="user-supplied weather CSV is not present")
@WINDOWS
def test_live_demo_heat_signal_and_site_isolation(tmp_path):
    path = run(WEATHER, tmp_path, 6000, 0.1, 0.1)
    journal = read_journal(path)
    demo = journal["demonstration"]
    assert demo["progress_before_pause"] > 0
    assert demo["progress_paused"] == demo["progress_after_paused_wait"]
    assert demo["progress_complete"] == 6000
    decisions = [event for event in journal["events"] if event["kind"] == "scheduler decision"]
    assert [event["run"] for event in decisions] == [True, False, True]
    request = next(event for event in journal["events"] if event["kind"] == "PAUSE requested")
    acknowledgement = next(
        event for event in journal["events"] if event["kind"] == "PAUSED acknowledged"
    )
    assert acknowledgement["monotonic_ns"] >= request["monotonic_ns"]
    assert request["monotonic_ns"] <= journal["intervals"][1]["end_monotonic_ns"]
    assert journal["intervals"][1]["end_monotonic_ns"] <= acknowledgement["monotonic_ns"]
    assigned = journal["thermal"]["site_results"]["weather-site"]
    other = journal["thermal"]["site_results"]["other-site"]
    assert sum(flow["recoverable_heat_kwh"] for flow in assigned) == pytest.approx(
        journal["energy"]["recoverable_heat_kwh_derived"]
    )
    assert all(flow["recoverable_heat_kwh"] == 0 for flow in other)
    assert (
        sum(interval["duration_ns"] for interval in journal["intervals"])
        == journal["active_ns_measured"]
    )


def test_live_reference_heat_and_deadline_policy():
    now = datetime(2025, 1, 1, tzinfo=UTC)
    rack = ComputeRack("rack", "site", Rack(1, 1, 0.8), 1, 1)
    common = {
        "now": now,
        "interval_end": now + timedelta(hours=1),
        "estimated_remaining_seconds": 900,
        "rack": rack,
    }
    assert (
        live_single_rack_decision(**common, deadline=now + timedelta(hours=2), opportunity_kwh=0)
        is None
    )
    assert live_single_rack_decision(
        **common, deadline=now + timedelta(hours=2), opportunity_kwh=1
    ) == now + timedelta(seconds=900)
    assert live_single_rack_decision(
        **common, deadline=now + timedelta(seconds=900), opportunity_kwh=0
    ) == now + timedelta(seconds=900)


def test_journal_replacement_is_atomic_and_stale_pid_is_not_reused(tmp_path, monkeypatch):
    path = tmp_path / "journal.json"
    _write_atomic(path, {"version": 1, "execution_id": "test", "status": "running"})

    def failed_replace(*args):
        raise OSError("replacement failed")

    monkeypatch.setattr("digitalheat_simulator.workload.weather_worker.os.replace", failed_replace)
    with pytest.raises(OSError, match="replacement failed"):
        _write_atomic(path, {"version": 1, "execution_id": "other"})
    assert read_journal(path)["execution_id"] == "test"
    assert "unknown" in read_journal(path)["recovery_notice"]
