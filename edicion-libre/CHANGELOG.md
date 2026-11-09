# Historial de la edición libre

La edición libre se versiona por separado de la aplicación de pago. Su código vive en `edicion-libre/` y las etiquetas Git usan `libre-v<versión>`. La primera incorporación al repositorio reúne el estado existente; las versiones anteriores se documentan como antecedentes y no se reconstruye un historial Git que no existía.

## 0.8.0 — Cotas del escaneo y preparación reutilizable

- Detección de planos opuestos y cilindros en cada STL nominal, selección versionada de cotas críticas y ajuste robusto local en la pieza escaneada. Cobertura insuficiente se informa sin inventar medidas.
- Perfiles inmutables de impresora, material, Otter y parámetros; calibración, fecha y medidas pertenecen a cada adquisición.
- Protocolo físico v2: Hausdorff discreto exacto con todos los puntos/vértices, separado del máximo superficial muestreado. Compatibilidad con resultados/reintentos v1.
- ΔD, cobertura, residuo y dispersión entre cotas en interfaz, CSV/JSON e informes. No se presenta el residuo como repetibilidad.
- 45 prompts como estudio aprobado; conjunto histórico de 60 intacto.
- Ensayos reproducibles con placa pública Trimesh, geometrías analíticas, contracción, espesor, agujeros, ruido y cobertura parcial. Migración aditiva con respaldo SQLite.

## 0.7.0 — Comparación de piezas escaneadas

- Protocolo físico independiente `ciel-metrologia-otter-v1`: archivos Otter STL/OBJ/PLY, nubes PCD/ASC/XYZ, unidades explícitas, registro rígido PCA/ICP y pares de puntos, sin ajuste de escala.
- Comparaciones anexas con originales/hashes, superposición 3D, métricas superficiales, cotas críticas repetidas, calibración, fotografías, figuras e informe HTML/CSV/ZIP.
- Entorno de metrología separado de los runtimes CAD congelados; migración aditiva con copia consistente de SQLite.
- Exportaciones de campañas manuales con tamaños reales, manufacturabilidad, trazas y actualización de archivos sin inferencia; se conserva la plantilla física rellenada.
- Comparaciones con resultados externos por caso: fuente/condiciones, hash del conjunto y criterios explícitos. La literatura histórica sigue identificada como contexto.
- Se mantienen los protocolos digitales, datasets congelados y entregas anteriores.

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
