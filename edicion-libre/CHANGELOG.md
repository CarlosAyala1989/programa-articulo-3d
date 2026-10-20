# Historial de la edición libre

La edición libre se versiona por separado de la aplicación de pago. Su código vive en `edicion-libre/` y las etiquetas Git usan `libre-v<versión>`. La primera incorporación al repositorio reúne el estado existente; las versiones anteriores se documentan como antecedentes y no se reconstruye un historial Git que no existía.

## 0.5.0 — Incorporación al repositorio

- Edición nativa Windows con Ollama existente, SQLite local y motores CadQuery, build123d y FreeCAD separados.
- Cinco modelos locales, 45 prompts y lote de 1.350 ejecuciones, con recuperación y conservación de campañas anteriores.
- Protocolo nativo v2 con contexto por modelo y salida sin tope fijo de la aplicación.
- Resultados, trazas, CSV/JSON, figuras PNG/SVG y exportaciones ZIP.
- Instalador, código fuente, dependencias fijadas y licencias del extractor incluidos.
- Versión independiente en `VERSION` y entregas verificables con SHA-256 en `entregas/0.5.0/`.

La aplicación nativa y el benchmark deben comprobarse en Windows. Las pruebas simuladas de la edición Docker, la inspección estática y la compilación del instalador no sustituyen esa comprobación.

## Antecedentes conservados

- **0.4.2:** corrección de la carpeta bin de FreeCAD y su intérprete Python; ver `REVISION_0.4.2.md`.
- **0.4.1:** extracción BCJ2 con 7-Zip verificado; ver `REVISION_0.4.1.md`.
- **0.4.0:** primera edición nativa de Windows; ver `REVISION_0.4.0.md`.
- **0.3.0:** edición Docker Desktop Hyper-V y Ollama Windows; se conserva su constructor `construir_instalador.py` y `VALIDACION_0.3.0.md`.

Para una nueva entrega, actualiza `VERSION`, los metadatos NSIS y `nativo/dependencias.json`, documenta el cambio aquí, reconstruye y verifica el instalador. Publica una nueva carpeta de entrega y una etiqueta nueva; conserva las anteriores. Un cambio del protocolo experimental requiere también una versión de protocolo y otra campaña, sin modificar campañas históricas.
