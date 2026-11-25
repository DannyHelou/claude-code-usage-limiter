"""Launch Claude inside a Windows Job Object before letting it run."""

import _winapi
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import shutil
import subprocess


kernel = ctypes.WinDLL("kernel32", use_last_error=True)
CREATE_SUSPENDED = 0x00000004


def bind(name, result, *arguments):
    function = getattr(kernel, name)
    function.restype = result
    function.argtypes = arguments
    return function


create_job = bind("CreateJobObjectW", wintypes.HANDLE, ctypes.c_void_p, wintypes.LPCWSTR)
assign_job = bind("AssignProcessToJobObject", wintypes.BOOL, wintypes.HANDLE, wintypes.HANDLE)
terminate_job = bind("TerminateJobObject", wintypes.BOOL, wintypes.HANDLE, wintypes.UINT)
resume_thread = bind("ResumeThread", wintypes.DWORD, wintypes.HANDLE)


class JobProcess:
    def __init__(self, job, process, command):
        self.job = job
        self.process = process
        self.command = command

    def wait(self, timeout=None):
        milliseconds = _winapi.INFINITE if timeout is None else int(timeout * 1000)
        if _winapi.WaitForSingleObject(self.process, milliseconds) == _winapi.WAIT_TIMEOUT:
            raise subprocess.TimeoutExpired(self.command, timeout)
        return _winapi.GetExitCodeProcess(self.process)

    def terminate_tree(self):
        if not terminate_job(self.job, 2):
            raise ctypes.WinError(ctypes.get_last_error())


@contextmanager
def start_job(command):
    executable = shutil.which(command[0])
    if not executable or not executable.lower().endswith(".exe"):
        raise ValueError(f"Put the native {command[0]}.exe on PATH for supervised launching.")
    job = create_job(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        process, thread, _, _ = _winapi.CreateProcess(
            executable, subprocess.list2cmdline([executable, *command[1:]]),
            None, None, False, CREATE_SUSPENDED, None, None, subprocess.STARTUPINFO(),
        )
        try:
            if not assign_job(job, process) or resume_thread(thread) == 0xFFFFFFFF:
                error = ctypes.WinError(ctypes.get_last_error())
                _winapi.TerminateProcess(process, 2)
                raise error
            yield JobProcess(job, process, command)
        finally:
            # A normal CLI exit can leave background descendants in its job.
            terminate_job(job, 2)
            _winapi.CloseHandle(thread)
            _winapi.CloseHandle(process)
    finally:
        _winapi.CloseHandle(job)
