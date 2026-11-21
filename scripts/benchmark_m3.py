"""Reproducible, time-limited synthetic annual M3 benchmark."""

import argparse
import ctypes
import multiprocessing
import sys
import threading
import time
import tracemalloc
from ctypes import wintypes
from datetime import UTC, datetime, timedelta

from digitalheat_simulator.domain.compute import ComputeRack, Job
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
from digitalheat_simulator.workload.scheduler import schedule


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _peak_working_set():
    if sys.platform != "win32":
        raise RuntimeError("this benchmark's process-memory measurement requires Windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_ProcessMemoryCounters),
        wintypes.DWORD,
    )
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(
        kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.PeakWorkingSetSize


def _worker(jobs_count, racks_count, peak, process_peak, results):
    tracemalloc.start()
    stop = threading.Event()

    def monitor():
        while not stop.wait(0.25):
            peak.value = tracemalloc.get_traced_memory()[1]
            process_peak.value = _peak_working_set()

    monitor_thread = threading.Thread(target=monitor, daemon=True)
    monitor_thread.start()
    started = time.perf_counter()
    try:
        start = datetime(2025, 1, 1, tzinfo=UTC)
        periods = tuple(
            Interval(start + timedelta(hours=i), start + timedelta(hours=i + 1))
            for i in range(8760)
        )
        thermal = Rack(1, 1, 0.8)
        demand = ThermalDemandSeries(
            "synthetic",
            tuple(DemandPoint(period, 0.8) for period in periods),
            Provenance("synthetic benchmark", unit="kWh"),
        )
        group = RackGroup(
            "racks",
            thermal,
            racks_count,
            tuple(OperationPoint(period, False) for period in periods),
        )
        scenario = Scenario((SiteGroup("site", "synthetic", 1, demand, (group,), 0, 0),))
        racks = tuple(
            ComputeRack(f"rack-{i:06}", "site", thermal, 2, 2) for i in range(racks_count)
        )
        year_seconds = 8760 * 3600
        jobs = tuple(
            Job(
                f"job-{i:06}",
                "synthetic",
                start + timedelta(seconds=i * year_seconds // jobs_count),
                start + timedelta(seconds=i * year_seconds // jobs_count + 6 * 3600),
                900,
                1,
                ("site",),
                True,
            )
            for i in range(jobs_count)
        )
        result = schedule(scenario, jobs, racks)
        peak.value = tracemalloc.get_traced_memory()[1]
        process_peak.value = _peak_working_set()
        results.put(("completed", time.perf_counter() - started, peak.value, len(result.segments)))
    finally:
        stop.set()
        monitor_thread.join()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", required=True, type=int)
    parser.add_argument("--racks", required=True, type=int)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    if args.jobs <= 0 or args.racks <= 0 or args.timeout <= 0:
        parser.error("jobs, racks and timeout must be positive")
    if sys.platform != "win32":
        parser.error("process-memory measurement currently requires Windows")
    peak = multiprocessing.Value("Q", 0)
    process_peak = multiprocessing.Value("Q", 0)
    results = multiprocessing.Queue()
    process = multiprocessing.Process(
        target=_worker, args=(args.jobs, args.racks, peak, process_peak, results)
    )
    process.start()
    process.join(args.timeout)
    if process.is_alive():
        process.terminate()
        process.join()
        print(
            f"jobs={args.jobs} racks={args.racks} status=timeout "
            f"seconds={args.timeout:.1f} sampled_python_peak_mib={peak.value / 1048576:.2f} "
            f"sampled_process_peak_mib={process_peak.value / 1048576:.2f}"
        )
        return
    if results.empty():
        raise RuntimeError(f"benchmark worker exited without a result: {process.exitcode}")
    status, elapsed, peak_bytes, detail = results.get()
    print(
        f"jobs={args.jobs} racks={args.racks} status={status} "
        f"seconds={elapsed:.3f} python_peak_mib={peak_bytes / 1048576:.2f} "
        f"process_peak_mib={process_peak.value / 1048576:.2f} detail={detail}"
    )
    if status != "completed":
        raise RuntimeError("benchmark worker failed")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
