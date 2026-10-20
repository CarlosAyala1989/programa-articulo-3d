"""Muestras de CPU/RAM de Windows y memoria informada por Ollama durante cada llamada."""

import statistics
import threading

import httpx
import psutil


class Muestreador:
    def __init__(self, etiqueta: str) -> None:
        self.etiqueta = etiqueta
        self.detener = threading.Event()
        self.cpu: list[float] = []
        self.ram: list[int] = []
        self.ollama_rss: list[int] = []
        self.vram: list[int] = []
        self.errores: set[str] = set()
        self.hilo = threading.Thread(target=self.muestrear, name="ciel-telemetria", daemon=True)

    def iniciar(self) -> None:
        self.hilo.start()

    def muestrear(self) -> None:
        with httpx.Client(base_url="http://127.0.0.1:11434", timeout=2, trust_env=False) as cliente:
            while not self.detener.is_set():
                try:
                    self.cpu.append(psutil.cpu_percent(interval=0.2))
                    self.ram.append(psutil.virtual_memory().used)
                    memoria = 0
                    encontrados = 0
                    for proceso in psutil.process_iter(["name", "memory_info"]):
                        try:
                            if "ollama" in (proceso.info["name"] or "").lower():
                                memoria += proceso.info["memory_info"].rss
                                encontrados += 1
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                    if encontrados:
                        self.ollama_rss.append(memoria)
                    respuesta = cliente.get("/api/ps")
                    respuesta.raise_for_status()
                    for modelo in respuesta.json().get("models", []):
                        if self.etiqueta in {modelo.get("name"), modelo.get("model")} and modelo.get("size_vram") is not None:
                            self.vram.append(int(modelo["size_vram"]))
                except Exception as error:
                    self.errores.add(type(error).__name__)
                self.detener.wait(1.8)

    def finalizar(self) -> dict:
        self.detener.set()
        self.hilo.join(timeout=4)
        return {"version": "ciel-telemetria-windows-v1", "intervalo_objetivo_s": 2,
            "muestras_cpu": len(self.cpu), "cpu_sistema_pct_media": statistics.mean(self.cpu) if self.cpu else None,
            "cpu_sistema_pct_maxima": max(self.cpu) if self.cpu else None,
            "ram_sistema_usada_pico_bytes": max(self.ram) if self.ram else None,
            "ram_ollama_rss_pico_bytes": max(self.ollama_rss) if self.ollama_rss else None,
            "vram_ollama_max_bytes": max(self.vram) if self.vram else None,
            "ambito_cpu_ram_sistema": "todo el equipo; incluye otras aplicaciones",
            "ambito_ram_ollama": "suma RSS de procesos cuyo nombre contiene ollama; puede contar memoria compartida",
            "ambito_vram": "size_vram declarado por /api/ps; no es una medición independiente de la GPU",
            "errores_muestreo": sorted(self.errores)}
