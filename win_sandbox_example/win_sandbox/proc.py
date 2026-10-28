"""Win7 兼容的进程沙箱原语。

安全顺序是全部价值所在::

    CreateProcessW(CREATE_SUSPENDED)
      -> 把子进程令牌完整性降到 Low
      -> 建 Job 并 AssignProcessToJobObject
      -> ResumeThread

任何一步失败都先杀掉挂起的进程再抛，绝不放一个未受控的进程跑起来。

刻意只用 Vista+ 就有的 API：没有 AppContainer（Win8+）、没有
JobObjectSecurityLimitInformation / NetRateControl（Win8+）、没有
SetProcessMitigationPolicy（Win8+）。整个模块不需要管理员权限。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import locale
import os
import re
import subprocess
import threading
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

# ---------------------------------------------------------------- 常量

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
CREATE_ALWAYS = 2
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x00000080

CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_NO_WINDOW = 0x08000000
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002

STARTF_USESTDHANDLES = 0x00000100
STARTF_USESHOWWINDOW = 0x00000001
SW_HIDE = 0

INFINITE = 0xFFFFFFFF
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
ERROR_ACCESS_DENIED = 5

TOKEN_QUERY = 0x0008
TOKEN_ADJUST_DEFAULT = 0x0080
TOKEN_INTEGRITY_LEVEL = 25  # TOKEN_INFORMATION_CLASS::TokenIntegrityLevel

SE_GROUP_INTEGRITY = 0x00000020

INTEGRITY_UNTRUSTED = 0x0000
INTEGRITY_LOW = 0x1000
INTEGRITY_MEDIUM = 0x2000
INTEGRITY_HIGH = 0x3000
INTEGRITY_SYSTEM = 0x4000

_INTEGRITY_NAMES = {
    INTEGRITY_UNTRUSTED: "Untrusted",
    INTEGRITY_LOW: "Low",
    INTEGRITY_MEDIUM: "Medium",
    INTEGRITY_HIGH: "High",
    INTEGRITY_SYSTEM: "System",
}

JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

JOB_OBJECT_UILIMIT_HANDLES = 0x00000001
JOB_OBJECT_UILIMIT_READCLIPBOARD = 0x00000002
JOB_OBJECT_UILIMIT_WRITECLIPBOARD = 0x00000004
JOB_OBJECT_UILIMIT_SYSTEMPARAMETERS = 0x00000008
JOB_OBJECT_UILIMIT_DISPLAYSETTINGS = 0x00000010
JOB_OBJECT_UILIMIT_GLOBALATOMS = 0x00000020
JOB_OBJECT_UILIMIT_DESKTOP = 0x00000040
JOB_OBJECT_UILIMIT_EXITWINDOWS = 0x00000080

JobObjectBasicAccountingInformation = 1
JobObjectBasicUIRestrictions = 4
JobObjectExtendedLimitInformation = 9

# ---------------------------------------------------------------- 结构体


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wt.DWORD),
        ("lpSecurityDescriptor", wt.LPVOID),
        ("bInheritHandle", wt.BOOL),
    ]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD),
        ("lpReserved", wt.LPWSTR),
        ("lpDesktop", wt.LPWSTR),
        ("lpTitle", wt.LPWSTR),
        ("dwX", wt.DWORD),
        ("dwY", wt.DWORD),
        ("dwXSize", wt.DWORD),
        ("dwYSize", wt.DWORD),
        ("dwXCountChars", wt.DWORD),
        ("dwYCountChars", wt.DWORD),
        ("dwFillAttribute", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("wShowWindow", wt.WORD),
        ("cbReserved2", wt.WORD),
        ("lpReserved2", wt.LPVOID),
        ("hStdInput", wt.HANDLE),
        ("hStdOutput", wt.HANDLE),
        ("hStdError", wt.HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [
        ("StartupInfo", STARTUPINFOW),
        ("lpAttributeList", wt.LPVOID),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wt.HANDLE),
        ("hThread", wt.HANDLE),
        ("dwProcessId", wt.DWORD),
        ("dwThreadId", wt.DWORD),
    ]


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", wt.LPVOID), ("Attributes", wt.DWORD)]


class TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = [("Label", SID_AND_ATTRIBUTES)]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wt.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wt.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wt.DWORD),
        ("SchedulingClass", wt.DWORD),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class JOBOBJECT_BASIC_UI_RESTRICTIONS(ctypes.Structure):
    _fields_ = [("UIRestrictionsClass", wt.DWORD)]


class JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_int64),
        ("TotalKernelTime", ctypes.c_int64),
        ("ThisPeriodTotalUserTime", ctypes.c_int64),
        ("ThisPeriodTotalKernelTime", ctypes.c_int64),
        ("TotalPageFaultCount", wt.DWORD),
        ("TotalProcesses", wt.DWORD),
        ("ActiveProcesses", wt.DWORD),
        ("TotalTerminatedProcesses", wt.DWORD),
    ]


# ---------------------------------------------------------------- 绑定

kernel32.CreateFileW.argtypes = [
    wt.LPCWSTR,
    wt.DWORD,
    wt.DWORD,
    ctypes.POINTER(SECURITY_ATTRIBUTES),
    wt.DWORD,
    wt.DWORD,
    wt.HANDLE,
]
kernel32.CreateFileW.restype = wt.HANDLE

kernel32.CreateProcessW.argtypes = [
    wt.LPCWSTR,
    wt.LPWSTR,
    wt.LPVOID,
    wt.LPVOID,
    wt.BOOL,
    wt.DWORD,
    wt.LPVOID,
    wt.LPCWSTR,
    ctypes.POINTER(STARTUPINFOW),
    ctypes.POINTER(PROCESS_INFORMATION),
]
kernel32.CreateProcessW.restype = wt.BOOL

kernel32.InitializeProcThreadAttributeList.argtypes = [
    wt.LPVOID,
    wt.DWORD,
    wt.DWORD,
    ctypes.POINTER(ctypes.c_size_t),
]
kernel32.InitializeProcThreadAttributeList.restype = wt.BOOL
kernel32.UpdateProcThreadAttribute.argtypes = [
    wt.LPVOID,
    wt.DWORD,
    ctypes.c_size_t,
    wt.LPVOID,
    ctypes.c_size_t,
    wt.LPVOID,
    wt.LPVOID,
]
kernel32.UpdateProcThreadAttribute.restype = wt.BOOL
kernel32.DeleteProcThreadAttributeList.argtypes = [wt.LPVOID]
kernel32.DeleteProcThreadAttributeList.restype = None

kernel32.CreateJobObjectW.argtypes = [wt.LPVOID, wt.LPCWSTR]
kernel32.CreateJobObjectW.restype = wt.HANDLE
kernel32.SetInformationJobObject.argtypes = [
    wt.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wt.DWORD,
]
kernel32.SetInformationJobObject.restype = wt.BOOL
kernel32.QueryInformationJobObject.argtypes = [
    wt.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wt.DWORD,
    ctypes.POINTER(wt.DWORD),
]
kernel32.QueryInformationJobObject.restype = wt.BOOL
kernel32.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
kernel32.AssignProcessToJobObject.restype = wt.BOOL
kernel32.TerminateJobObject.argtypes = [wt.HANDLE, wt.UINT]
kernel32.TerminateJobObject.restype = wt.BOOL

kernel32.GetCurrentProcess.restype = wt.HANDLE
kernel32.GetCurrentProcess.argtypes = []
kernel32.ResumeThread.argtypes = [wt.HANDLE]
kernel32.ResumeThread.restype = wt.DWORD
kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
kernel32.WaitForSingleObject.restype = wt.DWORD
kernel32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
kernel32.GetExitCodeProcess.restype = wt.BOOL
kernel32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
kernel32.TerminateProcess.restype = wt.BOOL
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.CloseHandle.restype = wt.BOOL
kernel32.IsProcessInJob.argtypes = [wt.HANDLE, wt.HANDLE, ctypes.POINTER(wt.BOOL)]
kernel32.IsProcessInJob.restype = wt.BOOL
kernel32.LocalFree.argtypes = [wt.HLOCAL]
kernel32.LocalFree.restype = wt.HLOCAL

advapi32.OpenProcessToken.argtypes = [
    wt.HANDLE,
    wt.DWORD,
    ctypes.POINTER(wt.HANDLE),
]
advapi32.OpenProcessToken.restype = wt.BOOL
advapi32.SetTokenInformation.argtypes = [
    wt.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wt.DWORD,
]
advapi32.SetTokenInformation.restype = wt.BOOL
advapi32.GetTokenInformation.argtypes = [
    wt.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wt.DWORD,
    ctypes.POINTER(wt.DWORD),
]
advapi32.GetTokenInformation.restype = wt.BOOL
advapi32.ConvertStringSidToSidW.argtypes = [
    wt.LPCWSTR,
    ctypes.POINTER(wt.LPVOID),
]
advapi32.ConvertStringSidToSidW.restype = wt.BOOL
advapi32.GetLengthSid.argtypes = [wt.LPVOID]
advapi32.GetLengthSid.restype = wt.DWORD
advapi32.GetSidSubAuthorityCount.argtypes = [wt.LPVOID]
advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
advapi32.GetSidSubAuthority.argtypes = [wt.LPVOID, wt.DWORD]
advapi32.GetSidSubAuthority.restype = ctypes.POINTER(wt.DWORD)

shell32.IsUserAnAdmin.argtypes = []
shell32.IsUserAnAdmin.restype = wt.BOOL


# ---------------------------------------------------------------- 小工具


def _last_error(what: str) -> OSError:
    err = ctypes.get_last_error()
    return OSError(err, f"{what} 失败: {ctypes.FormatError(err)}")


def _require(ok: object, what: str) -> None:
    if not ok:
        raise _last_error(what)


def integrity_name(level: int | None) -> str:
    """把完整性级别数值转成可读名字。"""
    if level is None:
        return "unknown"
    return f"{_INTEGRITY_NAMES.get(level, '?')}(0x{level:04x})"


def _sid_from_string(text: str) -> int:
    sid = wt.LPVOID()
    _require(
        advapi32.ConvertStringSidToSidW(text, ctypes.byref(sid)),
        "ConvertStringSidToSidW",
    )
    return sid.value


def _token_integrity(h_token: int) -> int:
    size = wt.DWORD(0)
    advapi32.GetTokenInformation(
        h_token, TOKEN_INTEGRITY_LEVEL, None, 0, ctypes.byref(size)
    )
    if size.value == 0:
        raise _last_error("GetTokenInformation(size)")
    buf = ctypes.create_string_buffer(size.value)
    _require(
        advapi32.GetTokenInformation(
            h_token, TOKEN_INTEGRITY_LEVEL, buf, size, ctypes.byref(size)
        ),
        "GetTokenInformation(TokenIntegrityLevel)",
    )
    label = ctypes.cast(buf, ctypes.POINTER(TOKEN_MANDATORY_LABEL)).contents
    count = advapi32.GetSidSubAuthorityCount(label.Label.Sid)
    index = count.contents.value - 1
    if index < 0:
        raise RuntimeError("令牌完整性 SID 没有子授权")
    sub = advapi32.GetSidSubAuthority(label.Label.Sid, index)
    return int(sub.contents.value)


def current_integrity() -> int:
    """当前进程的完整性级别（Low=0x1000 / Medium=0x2000 / High=0x3000）。"""
    h_token = wt.HANDLE()
    _require(
        advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(h_token)
        ),
        "OpenProcessToken(当前进程)",
    )
    try:
        return _token_integrity(h_token)
    finally:
        kernel32.CloseHandle(h_token)


def _process_integrity(h_process: int) -> int:
    h_token = wt.HANDLE()
    _require(
        advapi32.OpenProcessToken(h_process, TOKEN_QUERY, ctypes.byref(h_token)),
        "OpenProcessToken(子进程)",
    )
    try:
        return _token_integrity(h_token)
    finally:
        kernel32.CloseHandle(h_token)


def _lower_to_low(h_process: int) -> int:
    """把子进程令牌降到 Low，返回降级后的实际级别。

    子进程此刻还挂在 CREATE_SUSPENDED 上，令牌改完再 resume，不存在
    “先跑起来再降级”的窗口。
    """
    h_token = wt.HANDLE()
    _require(
        advapi32.OpenProcessToken(
            h_process,
            TOKEN_QUERY | TOKEN_ADJUST_DEFAULT,
            ctypes.byref(h_token),
        ),
        "OpenProcessToken(降完整性)",
    )
    sid = _sid_from_string("S-1-16-4096")  # Low Mandatory Level
    try:
        sid_len = advapi32.GetLengthSid(sid)
        size = ctypes.sizeof(TOKEN_MANDATORY_LABEL) + sid_len
        buf = ctypes.create_string_buffer(size)
        label = ctypes.cast(buf, ctypes.POINTER(TOKEN_MANDATORY_LABEL))
        label.contents.Label.Attributes = SE_GROUP_INTEGRITY
        label.contents.Label.Sid = sid
        _require(
            advapi32.SetTokenInformation(h_token, TOKEN_INTEGRITY_LEVEL, buf, size),
            "SetTokenInformation(TokenIntegrityLevel)",
        )
        return _token_integrity(h_token)
    finally:
        kernel32.LocalFree(sid)
        kernel32.CloseHandle(h_token)


def is_user_admin() -> bool:
    """当前进程是否以管理员身份运行（仅用于探测报告）。"""
    return bool(shell32.IsUserAnAdmin())


def process_in_job() -> bool:
    """当前进程是否已经在一个 Job 里（Win7 不支持嵌套 Job）。"""
    in_job = wt.BOOL()
    _require(
        kernel32.IsProcessInJob(
            kernel32.GetCurrentProcess(), None, ctypes.byref(in_job)
        ),
        "IsProcessInJob",
    )
    return bool(in_job.value)


# ---------------------------------------------------------------- Job


def _create_job(limits: SandboxLimits) -> int:
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise _last_error("CreateJobObjectW")

    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = (
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        | JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        | JOB_OBJECT_LIMIT_PROCESS_MEMORY
        | JOB_OBJECT_LIMIT_JOB_MEMORY
    )
    info.BasicLimitInformation.ActiveProcessLimit = limits.max_processes
    info.ProcessMemoryLimit = limits.memory_mb * 1024 * 1024
    info.JobMemoryLimit = limits.memory_mb * 1024 * 1024

    if not kernel32.SetInformationJobObject(
        job,
        JobObjectExtendedLimitInformation,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        err = _last_error("SetInformationJobObject(ExtendedLimit)")
        kernel32.CloseHandle(job)
        raise err

    ui = JOBOBJECT_BASIC_UI_RESTRICTIONS(
        JOB_OBJECT_UILIMIT_HANDLES
        | JOB_OBJECT_UILIMIT_READCLIPBOARD
        | JOB_OBJECT_UILIMIT_WRITECLIPBOARD
        | JOB_OBJECT_UILIMIT_SYSTEMPARAMETERS
        | JOB_OBJECT_UILIMIT_DISPLAYSETTINGS
        | JOB_OBJECT_UILIMIT_GLOBALATOMS
        | JOB_OBJECT_UILIMIT_DESKTOP
        | JOB_OBJECT_UILIMIT_EXITWINDOWS
    )
    if not kernel32.SetInformationJobObject(
        job,
        JobObjectBasicUIRestrictions,
        ctypes.byref(ui),
        ctypes.sizeof(ui),
    ):
        err = _last_error("SetInformationJobObject(BasicUIRestrictions)")
        kernel32.CloseHandle(job)
        raise err

    return job


def _assign_to_job(job: int, h_process: int) -> None:
    if kernel32.AssignProcessToJobObject(job, h_process):
        return
    err = ctypes.get_last_error()
    if err == ERROR_ACCESS_DENIED and process_in_job():
        raise OSError(
            err,
            "父进程已在一个 Job 中，Win7 不支持嵌套 Job；"
            "需要以 CREATE_BREAKAWAY_FROM_JOB 启动或让宿主退出 Job",
        )
    raise OSError(err, f"AssignProcessToJobObject 失败: {ctypes.FormatError(err)}")


# ---------------------------------------------------------------- 环境


_ENV_KEEP = (
    "PATH",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
    "LANG",
    "LC_ALL",
)


def sandbox_env(workdir: Path, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """构造子进程环境：只保留运行必需的变量，把 HOME/TEMP 全部重定向到工作区。

    ``workdir`` 必须**先**打好低完整性标签，否则这里新建的 ``.sandbox``
    会继承 Medium，低完整性进程写不进去。
    """
    src = dict(os.environ if base is None else base)
    env = {key: src[key] for key in _ENV_KEEP if key in src}

    home = workdir / ".sandbox" / "home"
    tmp = workdir / ".sandbox" / "tmp"
    home.mkdir(parents=True, exist_ok=True)
    tmp.mkdir(parents=True, exist_ok=True)

    env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "TEMP": str(tmp),
            "TMP": str(tmp),
            "MSYSTEM": "MINGW64",
            "MSYS2_PATH_TYPE": "inherit",
            "CHERE_INVOKING": "1",
        }
    )
    return env


def set_low_integrity_label(path: Path, *, recursive: bool = False) -> tuple[bool, str]:
    """给目录打低完整性标签（子项继承）。

    ``recursive=True`` 会连已有子项一起改（``/T``）—— 工作区里已经存在
    的项目文件是 Medium，不递归的话低完整性子进程改不了它们。

    返回 ``(是否成功, 细节)``。免管理员是否可行取决于目标机策略，
    所以返回值而不是抛异常 —— 探测脚本要把它当成一项能力来报告。
    """
    args = ["icacls", str(path), "/setintegritylevel", "(OI)(CI)L"]
    if recursive:
        args.append("/T")
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding=locale.getpreferredencoding(False),
            errors="replace",
        )
    except OSError as exc:  # pragma: no cover - 只在 icacls 缺失时发生
        return False, str(exc)
    detail = (result.stdout + result.stderr).strip()
    return result.returncode == 0, detail or f"rc={result.returncode}"


def _open_inheritable(path: str | Path, access: int, disposition: int) -> int:
    attrs = SECURITY_ATTRIBUTES()
    attrs.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES)
    attrs.lpSecurityDescriptor = None
    attrs.bInheritHandle = True
    handle = kernel32.CreateFileW(
        str(path),
        access,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        ctypes.byref(attrs),
        disposition,
        FILE_ATTRIBUTE_NORMAL,
        None,
    )
    if handle in (None, INVALID_HANDLE_VALUE):
        raise _last_error(f"CreateFileW({path})")
    return handle


def _env_block(env: Mapping[str, str]) -> ctypes.Array:
    items = [f"{key}={value}" for key, value in env.items() if key and "=" not in key]
    text = "\0".join(items) + "\0\0"
    buf = ctypes.create_unicode_buffer(len(text) + 1)
    ctypes.memmove(buf, text, len(text) * ctypes.sizeof(ctypes.c_wchar))
    return buf


_MSYS2_TOKEN_WARNING = re.compile(
    r"^\s*\d+ \[main\] .*cygheap_user::init: "
    r"NtSetInformationToken \(TokenDefaultDacl\), 0x[0-9A-Fa-f]+\s*$"
)


def clean_stderr(text: str) -> str:
    """滤掉 MSYS2 在低完整性令牌下的已知无害告警。

    ``usr/bin/bash.exe`` 启动时会给令牌重设 default DACL，低完整性下失败并
    打印一行 ``cygheap_user::init: NtSetInformationToken ... 0xC0000022``；
    bash 继续正常运行，但会污染每条命令的 stderr。
    """
    if "cygheap_user::init" not in text:
        return text
    lines = [line for line in text.splitlines() if not _MSYS2_TOKEN_WARNING.match(line)]
    return "\n".join(lines)


# ---------------------------------------------------------------- 公开 API


@dataclass(frozen=True)
class SandboxLimits:
    """Job 的资源上限。默认值按“跑构建 / 测试”估的，可按话题调整。"""

    max_processes: int = 64
    memory_mb: int = 2048
    timeout_s: float = 120.0


@dataclass
class RunResult:
    exit_code: int
    timed_out: bool
    stdout: str
    stderr: str
    child_integrity: int | None
    cancelled: bool = False


class SandboxProcess:
    """一个已经进了 Job 的子进程。``close()`` 会连同进程树一起收掉。"""

    def __init__(
        self,
        h_process: int,
        h_thread: int,
        h_job: int,
        pid: int,
        child_integrity: int | None,
    ) -> None:
        self._process = h_process
        self._thread = h_thread
        self._job = h_job
        self.pid = pid
        self.child_integrity = child_integrity
        self._closed = False

    def wait(
        self,
        timeout_s: float | None = None,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        """等待退出；``cancel_event`` 被置位时提前返回 ``False``（不杀进程）。

        调用方看到 ``False`` 后自己决定是超时还是取消，并负责 ``terminate()``。
        """
        if cancel_event is None:
            milliseconds = (
                INFINITE if timeout_s is None else max(0, int(timeout_s * 1000))
            )
            rc = kernel32.WaitForSingleObject(self._process, milliseconds)
            if rc == WAIT_OBJECT_0:
                return True
            if rc == WAIT_TIMEOUT:
                return False
            raise OSError(f"WaitForSingleObject 返回 0x{rc:08x}")

        deadline = None if timeout_s is None else time.monotonic() + max(0.0, timeout_s)
        while True:
            if cancel_event.is_set():
                return False
            if deadline is None:
                slice_ms = 200
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                slice_ms = max(1, min(200, int(remaining * 1000)))
            rc = kernel32.WaitForSingleObject(self._process, slice_ms)
            if rc == WAIT_OBJECT_0:
                return True
            if rc != WAIT_TIMEOUT:
                raise OSError(f"WaitForSingleObject 返回 0x{rc:08x}")

    def exit_code(self) -> int:
        code = wt.DWORD(0)
        _require(
            kernel32.GetExitCodeProcess(self._process, ctypes.byref(code)),
            "GetExitCodeProcess",
        )
        return int(code.value)

    def active_processes(self) -> int:
        """Job 里还活着的进程数。"""
        info = JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
        returned = wt.DWORD(0)
        _require(
            kernel32.QueryInformationJobObject(
                self._job,
                JobObjectBasicAccountingInformation,
                ctypes.byref(info),
                ctypes.sizeof(info),
                ctypes.byref(returned),
            ),
            "QueryInformationJobObject",
        )
        return int(info.ActiveProcesses)

    def terminate(self) -> None:
        """杀掉整棵进程树。"""
        if self._closed:
            return
        _require(kernel32.TerminateJobObject(self._job, 1), "TerminateJobObject")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        # 先关 Job：KILL_ON_JOB_CLOSE 保证没有漏网的子孙进程。
        if self._job:
            kernel32.CloseHandle(self._job)
        if self._thread:
            kernel32.CloseHandle(self._thread)
        if self._process:
            kernel32.CloseHandle(self._process)

    def __enter__(self) -> SandboxProcess:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def spawn(
    argv: Sequence[str],
    *,
    workdir: Path,
    env: Mapping[str, str],
    stdout_path: Path,
    stderr_path: Path,
    limits: SandboxLimits | None = None,
    low_integrity: bool = True,
) -> SandboxProcess:
    """在 Job 里启动一个进程；``low_integrity=True`` 时把它的令牌降到 Low。"""
    if not argv:
        raise ValueError("argv 不能为空")
    limits = limits or SandboxLimits()
    workdir = Path(workdir)
    stdout_path = Path(stdout_path)
    stderr_path = Path(stderr_path)
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)

    h_out = _open_inheritable(stdout_path, GENERIC_WRITE, CREATE_ALWAYS)
    h_err = _open_inheritable(stderr_path, GENERIC_WRITE, CREATE_ALWAYS)
    h_in = _open_inheritable("NUL", GENERIC_READ, OPEN_EXISTING)
    handles = (h_in, h_out, h_err)

    startup = STARTUPINFOEXW()
    startup.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW
    startup.StartupInfo.wShowWindow = SW_HIDE
    startup.StartupInfo.hStdInput = h_in
    startup.StartupInfo.hStdOutput = h_out
    startup.StartupInfo.hStdError = h_err

    info = PROCESS_INFORMATION()
    command_line = subprocess.list2cmdline([str(arg) for arg in argv])
    command_buf = ctypes.create_unicode_buffer(command_line)
    env_buf = _env_block(env)

    attr_buf = None
    try:
        # 只让子进程继承这三个句柄：bInheritHandles=True 会继承父进程里
        # 所有可继承句柄，不加白名单等于把宿主的管道 / socket 一起交出去。
        handle_array = (wt.HANDLE * len(handles))(*handles)
        attr_size = ctypes.c_size_t(0)
        kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(attr_size))
        if attr_size.value == 0:
            raise _last_error("InitializeProcThreadAttributeList(size)")
        attr_buf = ctypes.create_string_buffer(attr_size.value)
        startup.lpAttributeList = ctypes.cast(attr_buf, wt.LPVOID)
        _require(
            kernel32.InitializeProcThreadAttributeList(
                startup.lpAttributeList, 1, 0, ctypes.byref(attr_size)
            ),
            "InitializeProcThreadAttributeList",
        )
        _require(
            kernel32.UpdateProcThreadAttribute(
                startup.lpAttributeList,
                0,
                PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                handle_array,
                ctypes.sizeof(handle_array),
                None,
                None,
            ),
            "UpdateProcThreadAttribute(HANDLE_LIST)",
        )

        created = kernel32.CreateProcessW(
            str(argv[0]),
            command_buf,
            None,
            None,
            True,
            CREATE_SUSPENDED
            | CREATE_UNICODE_ENVIRONMENT
            | CREATE_NO_WINDOW
            | EXTENDED_STARTUPINFO_PRESENT,
            ctypes.cast(env_buf, ctypes.c_void_p),
            str(workdir),
            ctypes.cast(ctypes.byref(startup), ctypes.POINTER(STARTUPINFOW)),
            ctypes.byref(info),
        )
        if not created:
            raise _last_error("CreateProcessW")
    except BaseException:
        for handle in handles:
            kernel32.CloseHandle(handle)
        raise
    finally:
        if attr_buf is not None:
            kernel32.DeleteProcThreadAttributeList(startup.lpAttributeList)

    # 子进程已经拿到这三个句柄的副本，父进程侧可以关掉了。
    for handle in handles:
        kernel32.CloseHandle(handle)

    job = 0
    try:
        child_integrity = (
            _lower_to_low(info.hProcess)
            if low_integrity
            else _process_integrity(info.hProcess)
        )
        job = _create_job(limits)
        _assign_to_job(job, info.hProcess)
        if kernel32.ResumeThread(info.hThread) == 0xFFFFFFFF:
            raise _last_error("ResumeThread")
    except BaseException:
        # 绝不放一个没进 Job / 没降完整性的进程跑起来。
        # AssignProcessToJobObject 失败时进程还没进 Job，TerminateJobObject
        # 杀不到它，必须先 TerminateProcess。
        kernel32.TerminateProcess(info.hProcess, 1)
        if job:
            kernel32.TerminateJobObject(job, 1)
        kernel32.WaitForSingleObject(info.hProcess, 3000)
        if job:
            kernel32.CloseHandle(job)
        kernel32.CloseHandle(info.hThread)
        kernel32.CloseHandle(info.hProcess)
        raise

    return SandboxProcess(
        h_process=info.hProcess,
        h_thread=info.hThread,
        h_job=job,
        pid=int(info.dwProcessId),
        child_integrity=child_integrity,
    )


def _read_output(path: Path, max_bytes: int | None, encoding: str) -> str:
    """读取输出；超过上限时只读尾部，避免把几 GB 拉进宿主内存。"""
    if not max_bytes or max_bytes <= 0:
        try:
            return path.read_text(encoding=encoding, errors="replace")
        except OSError:
            return ""
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    if size <= max_bytes:
        try:
            return path.read_text(encoding=encoding, errors="replace")
        except OSError:
            return ""
    try:
        with path.open("rb") as handle:
            handle.seek(size - max_bytes)
            tail = handle.read().decode(encoding, errors="replace")
    except OSError:
        return ""
    return f"... [output truncated; showing last {max_bytes} bytes] ...\n{tail}"


def run_in_sandbox(
    command: str,
    *,
    shell: Sequence[str],
    workdir: Path,
    env: Mapping[str, str],
    limits: SandboxLimits | None = None,
    low_integrity: bool = True,
    max_output_bytes: int | None = None,
    cancel_event: threading.Event | None = None,
) -> RunResult:
    """跑一条命令并等它结束（输出落文件，不占管道）。

    ``shell`` 是命令前缀，例如 ``[bash, "-c"]`` 或 ``[cmd.exe, "/c"]``。
    沙箱原语本身不绑定任何 shell。

    ``max_output_bytes`` 限制单条命令读回宿主的内存；超出时只读尾部并加
    截断标记（完整输出文件在返回前删除，避免磁盘被单条命令撑爆）。

    ``cancel_event`` 被置位时立即杀掉整棵进程树并返回 ``cancelled=True`` ——
    UI 的停止按钮走这条路径。
    """
    limits = limits or SandboxLimits()
    workdir = Path(workdir)
    # 工具调用可能并行（execute_tools_parallel），输出文件必须一次一份。
    token = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
    stdout_path = workdir / ".sandbox" / f"stdout_{token}.txt"
    stderr_path = workdir / ".sandbox" / f"stderr_{token}.txt"

    process = spawn(
        [*shell, command],
        workdir=workdir,
        env=env,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        limits=limits,
        low_integrity=low_integrity,
    )
    try:
        exited = process.wait(limits.timeout_s, cancel_event)
        cancelled = not exited and cancel_event is not None and cancel_event.is_set()
        timed_out = not exited and not cancelled
        if not exited:
            process.terminate()
            process.wait(5.0)
        exit_code = process.exit_code()
        child_integrity = process.child_integrity
    finally:
        process.close()

    encoding = locale.getpreferredencoding(False)
    try:
        stdout = _read_output(stdout_path, max_output_bytes, encoding)
        stderr = _read_output(stderr_path, max_output_bytes, encoding)
    finally:
        for path in (stdout_path, stderr_path):
            try:
                path.unlink()
            except OSError:
                pass

    return RunResult(
        exit_code=exit_code,
        timed_out=timed_out,
        stdout=stdout,
        stderr=clean_stderr(stderr),
        child_integrity=child_integrity,
        cancelled=cancelled,
    )
