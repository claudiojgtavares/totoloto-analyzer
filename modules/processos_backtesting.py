"""Supervisão do ciclo de vida; NÃO é um mecanismo de exclusão (essa é MySQL)."""
import ctypes
import os
import signal
import uuid


class GrupoProcessos:
    """Windows Job Object: mata workers órfãos quando o coordenador morre.

    Só o coordenador retém o handle. Cada worker associa-se no initializer;
    se o coordenador morreu antes disso, OpenJobObject falha e não há trabalho.
    """
    def __init__(self):
        self.nome = "Totoloto-F04-" + uuid.uuid4().hex
        self.handle = None
        if os.name != "nt":
            return
        from ctypes import wintypes as w
        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", w.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", w.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount",
                       "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
        class EXTENDED(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        k.CreateJobObjectW.restype = w.HANDLE
        k.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        k.CloseHandle.argtypes = [w.HANDLE]
        self.kernel = k
        self.handle = k.CreateJobObjectW(None, self.nome)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = EXTENDED()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            erro = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise erro

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def associar_worker(nome, parent_pid):
    if os.name == "nt":
        from ctypes import wintypes as w
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenJobObjectW.argtypes = [w.DWORD, w.BOOL, w.LPCWSTR]
        k.OpenJobObjectW.restype = w.HANDLE
        k.GetCurrentProcess.restype = w.HANDLE
        k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        k.CloseHandle.argtypes = [w.HANDLE]
        handle = k.OpenJobObjectW(0x0001, False, nome)  # JOB_OBJECT_ASSIGN_PROCESS
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not k.AssignProcessToJobObject(handle, k.GetCurrentProcess()):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            k.CloseHandle(handle)
    else:
        # Linux (testes/CI): matar o worker se o pai morrer, incluindo a corrida inicial.
        import sys
        if not sys.platform.startswith("linux"):
            raise RuntimeError("O coordenador F-04 suporta Windows e Linux.")
        if ctypes.CDLL(None).prctl(1, signal.SIGKILL) != 0:
            raise RuntimeError("Não foi possível proteger os workers órfãos.")
        if os.getppid() != parent_pid:
            os.kill(os.getpid(), signal.SIGKILL)
