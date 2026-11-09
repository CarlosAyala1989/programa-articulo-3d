# Validación nativa 0.7.0

## Alcance implementado

Comparaciones físicas anexas a trabajos exitosos, protocolo `ciel-metrologia-otter-v1`, impresión manual, entradas STL/OBJ/PLY del Otter y nubes PCD/ASC/XYZ. Registro rígido sin ajuste de escala; matriz, versiones, muestras, originales y hashes conservados. Cotas críticas, fotografías, calibración y parámetros de impresión se registran por comparación. No se alteran los 60 casos congelados, límites digitales de uno/cinco intentos ni protocolos de campañas históricas.

## Comprobaciones

- **53 pruebas unittest correctas** en `ciel-metrologia-validacion:local`, sin red: las 37 anteriores y 16 de metrología, API, migración, exportaciones y resultados externos. SQLite temporal, IA/CAD simulados. Las pruebas geométricas sí ejecutan NumPy/SciPy/Trimesh/Rtree sobre geometrías sintéticas conocidas.
- Casos idénticos con distancia cero sin piso artificial del muestreo; recuperación de giro/traslación; conservación de contracción y puntos atípicos en las muestras evaluadas; transformación sin reflexión ni escala; formatos y unidades; errores dimensionales repetidos con desviación muestral; PNG/PLY/CSV y matrices fotográficas válidas; conservación de originales y verificación de hashes.
- Regresión de una caja contraída y girada: el refinamiento de superficie usa todas las correspondencias dentro del umbral para evitar desplazar la pieza hacia una cara por recorte de residuos. El recorte permanece solo en la inicialización/registro de puntos.
- API: carga asíncrona, rechazo de sobrescritura, calibración sin fecha, formatos inválidos y trabajos fallidos; interrupción/reintento y confirmación; ZIP con manifiesto verificable. La migración desde SQLite 0.6 crea copia consistente y conserva el resultado anterior.
- Campaña manual de un caso: manufacturabilidad, trazas, conjunto y tamaños reales; la plantilla física previamente rellenada se conserva. Resultados externos: mismo hash/casos/repeticiones/criterio, fuentes y condiciones; Compile Rate y fallo de CAD se calculan independientemente.
- **Integración HTTP real de API y servicio de metrología**, en un contenedor temporal y con datos explícitamente sintéticos: carga de una caja de 40 × 25 × 12 mm contraída 1 % y girada/trasladada, procesamiento, confirmación y ZIP con 17 archivos verificados. Hausdorff muestreado aproximadamente **0,23324 mm**, Chamfer cuadrático **0,0258475 mm²**; las tres medidas dimensionales sintéticas declaradas producen ΔD medio **−0,4 mm** y desviación **0,01 mm**. Estos números validan el cálculo; no son resultados de impresión o del escáner del usuario.
- Construcción Vite correcta; permanece el aviso de tamaño de Three.js. Revisión de la interfaz en temas claro/oscuro, escritorio 1440 px y móvil 390 px. Se probó carga desde selector de archivo y formulario de cotas con API real. Capturas `output/playwright/ciel-070-*.png`. Detector de los tres archivos nuevos de UI: sin hallazgos.
- Figuras con fuente DejaVu Unicode incluida y licencia, escalas en mm y PNG con metadatos de 300 dpi. El mapa es estimado por muestreo; no constituye un máximo continuo certificado. La precisión comercial del escáner no se transforma en incertidumbre de medida.
- Parser de PowerShell 7.4: sintaxis correcta de `preparar.ps1`. Descarga/resolución de wheels binarios para Windows x64/Python 3.11 de los requisitos nuevos, incluyendo Rtree; sin instalar ni cambiar los runtimes CAD congelados.

## Entrega y revisión final

- Instalador NSIS 0.7.0 compilado; `programa.zip`, manifiesto y SHA-256 en `entregas/0.7.0/`. Las tres pruebas de entrega verifican versión, ejecutable MZ, hashes, contenido Python y ausencia de archivos de secretos/datos de usuario. Se conservan las entregas anteriores.
- La revisión independiente puntuó como resueltos los dos ajustes finales: puntos del visor visibles en ambos temas/móvil y leyendas coherentes con cada modo. Su `ship` se limita a esos dos fixes. La revisión posterior de Métricas también puntuó como resueltos el botón tematizado y el enlace de plantilla; se verificó su confirmación de actualización con la API real y las descargas de campaña. El registro de continuidad del diseño se guarda en `.impeccable/review/verificacion-sistema-070.md`.

## Límites de la validación

No se ejecutó el instalador en el Windows de destino, ni inferencias, motores CAD nativos, impresión o escaneos reales del usuario. La validación sintética y los wheels disponibles no sustituyen esa comprobación. Hace falta probar la actualización sobre la instalación del usuario y al menos un escaneo real del Otter, revisando la alineación y la calibración.

Las cotas críticas se calculan a partir de las mediciones declaradas por el usuario. La envolvente XYZ automática se identifica por separado y no se presenta como un diámetro o espesor. Las filas sin cotas/fotos/calibración conservan la ausencia; una alineación confirmada no certifica por sí misma la pieza.
