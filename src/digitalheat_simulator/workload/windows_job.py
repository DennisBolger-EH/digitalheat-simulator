"""Windows kill-on-close containment for the registered local worker."""

import ctypes
import os
from ctypes import wintypes


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_longlong),
        ("job_time", ctypes.c_longlong),
        ("flags", wintypes.DWORD),
        ("minimum_working_set", ctypes.c_size_t),
        ("maximum_working_set", ctypes.c_size_t),
        ("active_process_limit", wintypes.DWORD),
        ("affinity", ctypes.c_size_t),
        ("priority_class", wintypes.DWORD),
        ("scheduling_class", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_ulonglong)
        for name in (
            "read_operations",
            "write_operations",
            "other_operations",
            "read_bytes",
            "write_bytes",
            "other_bytes",
        )
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", _BasicLimits),
        ("io", _IoCounters),
        ("process_memory", ctypes.c_size_t),
        ("job_memory", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t),
        ("peak_job_memory", ctypes.c_size_t),
    ]


class WindowsJob:
    """Own a job handle; closing it terminates every process assigned to it."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("the real worker requires Windows job-object containment")
        self._api = ctypes.WinDLL("kernel32", use_last_error=True)
        self._api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self._api.CreateJobObjectW.restype = wintypes.HANDLE
        self._api.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self._api.SetInformationJobObject.restype = wintypes.BOOL
        self._api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self._api.AssignProcessToJobObject.restype = wintypes.BOOL
        self._api.CloseHandle.argtypes = [wintypes.HANDLE]
        self._api.CloseHandle.restype = wintypes.BOOL
        self._api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._api.OpenProcess.restype = wintypes.HANDLE
        self._api.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self._api.TerminateProcess.restype = wintypes.BOOL
        self._api.IsProcessInJob.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.BOOL),
        ]
        self._api.IsProcessInJob.restype = wintypes.BOOL
        self._api.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        self._api.GetProcessTimes.restype = wintypes.BOOL
        self.handle = self._api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self._api.SetInformationJobObject(
            self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            error = ctypes.get_last_error()
            self.close()
            raise ctypes.WinError(error)

    def assign(self, process_handle: int) -> None:
        if not self._api.AssignProcessToJobObject(self.handle, process_handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def contain_worker(self, pid: int) -> int:
        """Contain a launcher-created worker and return its Windows creation FILETIME."""
        handle = self._api.OpenProcess(0x100 | 0x1 | 0x1000, False, pid)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            in_job = wintypes.BOOL()
            if not self._api.IsProcessInJob(handle, self.handle, ctypes.byref(in_job)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not in_job.value:
                self.assign(handle)
            creation, exit_time, kernel, user = (wintypes.FILETIME() for _ in range(4))
            if not self._api.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            return (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        except OSError:
            if not self._api.TerminateProcess(handle, 1):
                raise ctypes.WinError(ctypes.get_last_error())
            raise
        finally:
            self._api.CloseHandle(handle)

    def close(self) -> None:
        if self.handle:
            handle, self.handle = self.handle, None
            if not self._api.CloseHandle(handle):
                raise ctypes.WinError(ctypes.get_last_error())
