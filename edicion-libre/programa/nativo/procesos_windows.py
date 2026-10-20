"""Límites de procesos CAD mediante Job Objects nativos de Windows, sin hipervisor."""

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path


class LimitesBasicos(ctypes.Structure):
    _fields_ = [("tiempo_proceso", ctypes.c_int64), ("tiempo_trabajo", ctypes.c_int64),
        ("banderas", wintypes.DWORD), ("memoria_minima", ctypes.c_size_t), ("memoria_maxima", ctypes.c_size_t),
        ("procesos_activos", wintypes.DWORD), ("afinidad", ctypes.c_size_t),
        ("prioridad", wintypes.DWORD), ("planificacion", wintypes.DWORD)]


class ContadoresIO(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in ("lecturas", "escrituras", "otros", "bytes_leidos", "bytes_escritos", "bytes_otros")]


class LimitesExtendidos(ctypes.Structure):
    _fields_ = [("basicos", LimitesBasicos), ("io", ContadoresIO), ("memoria_proceso", ctypes.c_size_t),
        ("memoria_trabajo", ctypes.c_size_t), ("pico_proceso", ctypes.c_size_t), ("pico_trabajo", ctypes.c_size_t)]


class Contabilidad(ctypes.Structure):
    _fields_ = [("tiempo_usuario", ctypes.c_int64), ("tiempo_kernel", ctypes.c_int64),
        ("periodo_usuario", ctypes.c_int64), ("periodo_kernel", ctypes.c_int64),
        ("fallos_pagina", wintypes.DWORD), ("procesos_total", wintypes.DWORD),
        ("procesos_activos", wintypes.DWORD), ("procesos_terminados", wintypes.DWORD)]


class TrabajoWindows:
    def __init__(self, memoria_bytes: int | None = None, limitar_cpu: bool = False) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Los procesos nativos de esta edición solo se ejecutan en Windows")
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.api.CreateJobObjectW.restype = wintypes.HANDLE
        self.api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.api.SetInformationJobObject.restype = wintypes.BOOL
        self.api.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
        self.api.QueryInformationJobObject.restype = wintypes.BOOL
        self.api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.api.AssignProcessToJobObject.restype = wintypes.BOOL
        self.api.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.api.TerminateJobObject.restype = wintypes.BOOL
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api.CloseHandle.restype = wintypes.BOOL
        self.api.GetCurrentProcess.restype = wintypes.HANDLE
        self.api.GetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limites = LimitesExtendidos()
        limites.basicos.banderas = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        self.afinidad = None
        if memoria_bytes:
            limites.basicos.banderas |= 0x100 | 0x200
            limites.memoria_proceso = limites.memoria_trabajo = memoria_bytes
        if limitar_cpu:
            proceso, sistema = ctypes.c_size_t(), ctypes.c_size_t()
            if not self.api.GetProcessAffinityMask(self.api.GetCurrentProcess(), ctypes.byref(proceso), ctypes.byref(sistema)):
                self.cerrar()
                raise ctypes.WinError(ctypes.get_last_error())
            bits = [1 << n for n in range(64) if proceso.value & (1 << n)][:2]
            limites.basicos.afinidad = sum(bits)
            limites.basicos.banderas |= 0x10
            self.afinidad = [n for n in range(64) if limites.basicos.afinidad & (1 << n)]
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limites), ctypes.sizeof(limites)):
            error = ctypes.get_last_error()
            self.cerrar()
            raise ctypes.WinError(error)

    def asignar(self, proceso: subprocess.Popen) -> None:
        if not self.api.AssignProcessToJobObject(self.handle, wintypes.HANDLE(int(proceso._handle))):
            raise ctypes.WinError(ctypes.get_last_error())

    def metricas(self) -> dict:
        limites, tiempos = LimitesExtendidos(), Contabilidad()
        if not self.api.QueryInformationJobObject(self.handle, 9, ctypes.byref(limites), ctypes.sizeof(limites), None):
            raise ctypes.WinError(ctypes.get_last_error())
        if not self.api.QueryInformationJobObject(self.handle, 1, ctypes.byref(tiempos), ctypes.sizeof(tiempos), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return {"memoria_pico_proceso_bytes": limites.pico_proceso, "memoria_pico_trabajo_bytes": limites.pico_trabajo,
            "cpu_usuario_segundos": tiempos.tiempo_usuario / 10_000_000, "cpu_kernel_segundos": tiempos.tiempo_kernel / 10_000_000,
            "procesadores_permitidos": self.afinidad, "procesos_creados": tiempos.procesos_total}

    def terminar(self) -> None:
        if self.handle:
            self.api.TerminateJobObject(self.handle, 1)

    def cerrar(self) -> None:
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


def ejecutar_limitado(argumentos: list[str], entorno: dict, carpeta: Path, limite_s: float = 100) -> tuple[dict, dict]:
    trabajo = TrabajoWindows(4 * 1024 ** 3, limitar_cpu=True)
    proceso = None
    inicio = time.monotonic()
    salida = carpeta / "proceso.log"
    try:
        with salida.open("wb") as registro:
            proceso = subprocess.Popen(argumentos, cwd=carpeta, env=entorno,
                stdout=registro, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                trabajo.asignar(proceso)
            except Exception:
                proceso.kill()
                proceso.wait()
                raise
            # El hijo espera este archivo antes de importar y ejecutar el código recibido.
            (carpeta / "autorizado").write_text("continuar", encoding="ascii")
            agotado = False
            while proceso.poll() is None:
                if time.monotonic() - inicio > limite_s or salida.stat().st_size > 10_000_000:
                    agotado = True
                    trabajo.terminar()
                    proceso.wait(timeout=10)
                    break
                time.sleep(0.1)
        mediciones = {**trabajo.metricas(), "duracion_proceso_segundos": time.monotonic() - inicio,
            "codigo_salida": proceso.returncode, "limite_memoria_bytes": 4 * 1024 ** 3,
            "limite_tiempo_segundos": limite_s, "aislamiento": "proceso nativo con revisión AST; Job Object no restringe permisos de archivos o red"}
        ruta = carpeta / "respuesta.json"
        if agotado:
            return {"correcto": False, "fase_error": "tiempo", "diagnostico": "El proceso CAD excedió el tiempo o el límite de salida",
                "sintaxis_valida": True, "ejecucion_correcta": False, "cad_valido": None, "exportacion_valida": None}, mediciones
        if proceso.returncode != 0 or not ruta.is_file() or ruta.stat().st_size > 35_000_000:
            texto = salida.read_bytes()[-3000:].decode("utf-8", "replace")
            return {"correcto": False, "fase_error": "proceso", "diagnostico": f"El motor CAD terminó con código {proceso.returncode}. {texto}",
                "sintaxis_valida": True, "ejecucion_correcta": False, "cad_valido": None, "exportacion_valida": None}, mediciones
        import json
        return json.loads(ruta.read_text(encoding="utf-8")), mediciones
    finally:
        trabajo.cerrar()
        if proceso and proceso.poll() is None:
            proceso.wait(timeout=10)
