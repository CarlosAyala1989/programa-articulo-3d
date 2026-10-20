"""Puente Linux/macOS sin dependencias: python -m aplicacion.puente_cli --socket RUTA."""

import argparse
import base64
import errno
import json
import os
import signal
import socket
import socketserver
import stat
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from aplicacion.cli_suscripcion import ErrorCLI, MODELOS_SUSCRIPCION, ejecutar_cli, ejecutable_cli, proveedor_cli, validar_esfuerzo_cli
from aplicacion.catalogo_cli import consultar_catalogo_cli


class ManejadorCLI(BaseHTTPRequestHandler):
    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(30)

    def log_message(self, formato: str, *argumentos) -> None:
        pass  # No registrar solicitudes, respuestas ni diagnósticos de autenticación.

    def responder(self, estado: int, datos: dict) -> None:
        contenido = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(estado)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(contenido)))
        self.end_headers()
        try:
            self.wfile.write(contenido)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self) -> None:
        if self.path == "/modelos":
            self.responder(200, {p: consultar_catalogo_cli(p) for p in MODELOS_SUSCRIPCION})
            return
        if self.path != "/salud":
            self.responder(404, {"error": "Ruta no disponible"})
            return
        self.responder(200, {"estado": "disponible", "transporte": "socket_unix",
            "instalados": {m: bool(ejecutable_cli(m)) for m in MODELOS_SUSCRIPCION},
            "sesion_comprobada": False})

    def do_POST(self) -> None:
        if self.path != "/generar":
            self.responder(404, {"error": "Ruta no disponible"})
            return
        try:
            longitud = int(self.headers.get("Content-Length", "0"))
            if longitud <= 0:
                raise ValueError
            solicitud = json.loads(self.rfile.read(longitud))
            modelo, mensajes = solicitud["modelo"], solicitud["mensajes"]
            proveedor = proveedor_cli(modelo)
            if proveedor is None or not isinstance(mensajes, list):
                raise ValueError
            if "::" in modelo and modelo not in consultar_catalogo_cli(proveedor)["modelos"]:
                raise ValueError
            esfuerzo = solicitud.get("esfuerzo_razonamiento")
            if esfuerzo is not None:
                validar_esfuerzo_cli(modelo, esfuerzo, consultar_catalogo_cli(proveedor)["modelos"].get(modelo, {}))
            if any(not isinstance(m, dict) for m in mensajes):
                raise ValueError
            imagenes = [base64.b64decode(i, validate=True) for i in solicitud.get("imagenes_png", [])]
            if len(imagenes) > 4 or any(not i.startswith(b"\x89PNG\r\n\x1a\n") for i in imagenes):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            self.responder(422, {"error": "Solicitud CLI inválida"})
            return
        if not self.server.turno.acquire(blocking=False):
            self.responder(409, {"error": "Puente CLI ocupado; la solicitud no se ejecutó", "codigo": "busy"})
            return
        try:
            respuesta = (ejecutar_cli(modelo, mensajes, imagenes, esfuerzo_razonamiento=esfuerzo)
                         if esfuerzo is not None else ejecutar_cli(modelo, mensajes, imagenes))
            self.responder(200, respuesta)
        except ErrorCLI as error:
            self.responder(503, {"error": str(error), "codigo": error.codigo})
        except Exception:
            self.responder(503, {"error": "El puente CLI no pudo completar la solicitud"})
        finally:
            self.server.turno.release()


def _interrumpir(*_) -> None:
    raise KeyboardInterrupt


def _retirar_socket_obsoleto(ruta: Path) -> None:
    try:
        datos = ruta.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISSOCK(datos.st_mode) or datos.st_uid != os.getuid():
        raise SystemExit("La ruta del puente debe ser un socket del usuario actual")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conexion:
        conexion.settimeout(1)
        try:
            conexion.connect(str(ruta))
        except OSError as error:
            if error.errno == errno.ENOENT:
                return
            if error.errno != errno.ECONNREFUSED:
                raise SystemExit("No se pudo comprobar el socket existente del puente") from None
        else:
            raise SystemExit("El puente CLI ya está en ejecución")
    ruta.unlink(missing_ok=True)


def iniciar_puente(ruta: str) -> None:
    if os.name != "posix":
        raise SystemExit("En Windows usa CLI_LOCAL_HABILITADO=1 con el backend nativo")
    socket = Path(ruta).expanduser().absolute()
    socket.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.umask(0o077)
    signal.signal(signal.SIGTERM, _interrumpir)
    # Serializar el arranque evita que dos procesos retiren el mismo socket.
    import fcntl
    with socket.with_suffix(".lock").open("a") as bloqueo:
        try:
            fcntl.flock(bloqueo, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("El puente CLI ya está en ejecución") from None
        _retirar_socket_obsoleto(socket)
        with socketserver.ThreadingUnixStreamServer(str(socket), ManejadorCLI) as servidor:
            os.chmod(socket, 0o600)
            servidor.turno = threading.Lock()
            servidor.timeout = 5
            try:
                servidor.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                socket.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Puente local de suscripciones para Agente Ciel")
    parser.add_argument("--socket", required=True)
    iniciar_puente(parser.parse_args().socket)
