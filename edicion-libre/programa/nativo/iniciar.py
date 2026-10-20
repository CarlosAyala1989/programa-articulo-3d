"""Arranque completo de Windows: servicios locales, SQLite y un trabajador secuencial."""

import argparse
import ctypes
import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path


def configurar(raiz: Path, resultados: Path) -> None:
    programa = Path(__file__).resolve().parents[1]
    datos = raiz / "datos"
    datos.mkdir(parents=True, exist_ok=True)
    resultados.mkdir(parents=True, exist_ok=True)
    (datos / "artefactos").mkdir(exist_ok=True)
    perfiles = json.loads((programa / "datos/modelos_windows_nativos_v1.json").read_text(encoding="utf-8"))
    os.environ.update({"CIEL_MODO_NATIVO": "1", "CIEL_AUTOMATICO": "1", "PYTHONUTF8": "1",
        "URL_BASE_DATOS": "sqlite:///" + (datos / "ciel.sqlite").as_posix(),
        "DIRECTORIO_ARTEFACTOS": str(datos / "artefactos"), "DIRECTORIO_RESULTADOS": str(resultados),
        "CIEL_RUNTIMES_NATIVOS": str(raiz / "runtimes_nativos.json"),
        "CIEL_REGISTRO_MODELOS": str(datos / "modelos_instalados.json"),
        "CIEL_DIRECTORIO_WEB": str(programa / "interfaz/dist"),
        "URL_SUPERVISOR": "http://127.0.0.1:8021", "URL_EVALUADOR": "http://127.0.0.1:8022",
        "URL_OLLAMA": "http://127.0.0.1:11434", "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
        "DEEPSEEK_API_KEY": "", "NVIDIA_API_KEY": "", "CLI_LOCAL_HABILITADO": "0"})
    for modelo in perfiles["modelos"]:
        os.environ["OLLAMA_" + modelo["codigo"]] = modelo["etiqueta"]


def esperar(url: str, proceso=None) -> dict:
    for _ in range(90):
        if proceso and proceso.poll() is not None:
            raise RuntimeError(f"El servicio {url} terminó; consulta su registro")
        try:
            with urllib.request.urlopen(url, timeout=2) as respuesta:
                return json.load(respuesta)
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"El servicio no respondió: {url}")


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("Esta edición ejecuta las 1.350 pruebas solamente en Windows. No se inicia en Ubuntu.")
    parser = argparse.ArgumentParser()
    parser.add_argument("--raiz", type=Path, required=True)
    parser.add_argument("--resultados", type=Path, required=True)
    argumentos = parser.parse_args()
    raiz, resultados = argumentos.raiz.resolve(), argumentos.resultados.resolve()
    api_windows = ctypes.WinDLL("kernel32", use_last_error=True)
    api_windows.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    api_windows.CreateMutexW.restype = ctypes.c_void_p
    api_windows.CloseHandle.argtypes = [ctypes.c_void_p]
    mutex = api_windows.CreateMutexW(None, False, "Local\\AgenteCielNativo")
    if not mutex:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        api_windows.CloseHandle(mutex)
        webbrowser.open("http://127.0.0.1:8020")
        return
    procesos, trabajos, registros = [], [], []
    servidor = None
    errores_arranque = []
    try:
        configurar(raiz, resultados)
        logs = raiz / "registros"
        logs.mkdir(exist_ok=True)
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
            handlers=[logging.FileHandler(logs / "aplicacion.log", encoding="utf-8"), logging.StreamHandler()])
        from nativo.modelos import registrar_modelos
        registrar_modelos(Path(__file__).resolve().parents[1], Path(os.environ["CIEL_REGISTRO_MODELOS"]))
        from nativo.procesos_windows import TrabajoWindows
        config = json.loads((raiz / "runtimes_nativos.json").read_text(encoding="utf-8"))
        servicios = [(str(raiz / "entornos/api/Scripts/python.exe"), "nativo.supervisor:aplicacion", 8021),
            (config["motores"]["cadquery"]["python"], "evaluador.api:aplicacion", 8022)]
        for python, aplicacion, puerto in servicios:
            registro = (logs / f"servicio-{puerto}.log").open("ab")
            registros.append(registro)
            trabajo = TrabajoWindows()
            trabajos.append(trabajo)
            proceso = subprocess.Popen([python, "-m", "uvicorn", aplicacion, "--host", "127.0.0.1", "--port", str(puerto)],
                cwd=Path(__file__).resolve().parents[1], env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                stdout=registro, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            procesos.append(proceso)
            trabajo.asignar(proceso)
            esperar(f"http://127.0.0.1:{puerto}/salud", proceso)
        import uvicorn
        from aplicacion.api import aplicacion
        from aplicacion.base_datos import crear_tablas
        crear_tablas()
        from aplicacion.proveedores import modelos_configurados, verificar_modelo_local
        for modelo in modelos_configurados():
            verificar_modelo_local(modelo)
        servidor = uvicorn.Server(uvicorn.Config(aplicacion, host="127.0.0.1", port=8020, log_level="info"))

        def arrancar_lote() -> None:
            try:
                esperar("http://127.0.0.1:8020/api/salud")
                from aplicacion.tareas_nativas import COLA
                from aplicacion.iniciar_trabajador import preparar_reinicio
                COLA.iniciar()
                preparar_reinicio(programar=True)
                logging.info("Lote nativo: 45 prompts × 5 modelos × 3 motores × 2 modos = 1.350 ejecuciones")
                logging.info("SQLite: %s; resultados: %s", raiz / "datos/ciel.sqlite", resultados)
                webbrowser.open("http://127.0.0.1:8020")
            except Exception as error:
                errores_arranque.append(error)
                logging.exception("No se pudo preparar el lote; no se iniciaron nuevas ejecuciones")
                servidor.should_exit = True

        threading.Thread(target=arrancar_lote, daemon=True).start()
        servidor.run()
        if errores_arranque:
            raise RuntimeError(f"No se pudo iniciar el lote: {errores_arranque[0]}")
    finally:
        if servidor:
            servidor.should_exit = True
        if "aplicacion.tareas_nativas" in sys.modules:
            from aplicacion.tareas_nativas import COLA
            COLA.cerrar()
        for trabajo in trabajos:
            trabajo.cerrar()
        for proceso in procesos:
            if proceso.poll() is None:
                try:
                    proceso.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proceso.kill()
        for registro in registros:
            registro.close()
        api_windows.CloseHandle(mutex)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Aplicación detenida. El próximo arranque recupera el checkpoint local.")
    except Exception as error:
        logging.exception("Error del arranque nativo")
        texto = f"{type(error).__name__}: {error}"
        if sys.platform == "win32":
            raiz = Path(os.environ.get("LOCALAPPDATA", ".")) / "AgenteCielNativo"
            raiz.mkdir(parents=True, exist_ok=True)
            (raiz / "ultimo-error.txt").write_text(texto + "\nConsulta registros/aplicacion.log", encoding="utf-8")
            ctypes.windll.user32.MessageBoxW(None, texto + f"\n\nRegistro: {raiz / 'registros/aplicacion.log'}", "Agente Ciel Nativo 0.5.0", 0x10)
        raise SystemExit(1)
