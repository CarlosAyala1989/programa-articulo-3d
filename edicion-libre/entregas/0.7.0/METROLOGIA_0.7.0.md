# Comparar una pieza impresa con su modelo virtual

La edición nativa 0.7.0 incorpora `ciel-metrologia-otter-v1`. La impresión es manual: Ciel no envía trabajos a una impresora ni controla el escáner. El usuario aporta los archivos que exportó desde CrealityScan. Las comparaciones se anexan al trabajo y no alteran su CAD, prompts, intentos, campaña ni éxito técnico.

## Actualizar Windows

1. Pausa la campaña y espera a que termine la generación en curso. Cierra la aplicación y su consola/preparación; cerrar la pestaña no detiene los servicios.
2. Ejecuta `Agente-Ciel-Nativo-0.7.0-Setup.exe` con el mismo usuario. Conserva datos y resultados anteriores.
3. La preparación añade un entorno Python independiente para metrología. No cambia los requisitos de CadQuery, build123d o FreeCAD ni sus identificadores congelados. Necesita internet para descargar las dependencias nuevas.
4. Comprueba **v0.7.0** en la cabecera. Si hace falta, recarga con Ctrl+F5.

Antes de añadir las tablas de comparaciones y resultados externos, una base SQLite histórica recibe una copia consistente `ciel.sqlite.antes-0.7.0-<fecha>.bak`. Las tablas antiguas y sus registros se conservan.

## Flujo de trabajo

1. En **Historial**, abre un trabajo exitoso. Descarga su STL, lamínalo e imprímelo por tu cuenta.
2. Calibra el CR-Scan Otter con su placa y el procedimiento del fabricante. Registra la fecha y el resultado de esa comprobación.
3. Escanea la pieza. Exporta desde CrealityScan **STL, OBJ o PLY**, con las unidades conocidas. Retira la mesa, soportes ajenos y fondo antes de exportar. Registra cualquier suavizado, relleno de agujeros u otro procesamiento aplicado en las notas.
4. En el resultado de Ciel abre **Comparar resultado con una pieza escaneada → Cargar un nuevo escaneo**. Selecciona el archivo y sus unidades. También se admiten nubes PCD ASCII/binarias sin comprimir, ASC y XYZ. Los archivos de proyecto de CrealityScan no se interpretan directamente.
5. Indica un nombre de pieza/réplica. Opcionalmente añade una foto, datos de impresión, software/serie del escáner, fechas, cotas críticas y medidas repetidas.
6. Pulsa **Comparar escaneo con este modelo**. La carga admite hasta 250 MB; las fotos PNG/JPG/WebP, hasta 20 MB y 40 megapíxeles. El cálculo continúa en segundo plano sin consultar modelos de IA.
7. Revisa **Desviaciones**, **Superposición** y **Modelo virtual**. Comprueba orientación, coincidencia de detalles y cobertura. Pulsa **He revisado y confirmo la alineación** cuando corresponda.
8. Descarga el ZIP de la comparación. Desde **Métricas** también puedes descargar la manufacturabilidad y el conjunto de entregables físicos de una campaña. Los ZIP completos de trabajos/campañas incluyen sus comparaciones físicas como paquetes anexos.

Cada escaneo nuevo crea otra comparación. Un escaneo ya recibido y un cálculo terminado no se sustituyen al cargar otro. Si se cierra la aplicación durante el procesamiento, el registro muestra la interrupción y permite reintentar el mismo archivo. Si la carga quedó incompleta, crea una comparación nueva.

## Alineación y unidades

La conversión de unidades es explícita: mm ×1, cm ×10, m ×1000, pulgadas ×25,4. Después solo se aplican rotación y traslación. **No se estima ni corrige la escala de la impresión.**

La alineación automática prueba 24 orientaciones de ejes principales y una inicialización por centroides; selecciona cinco candidatas para ICP rígido multiumbral y refina con correspondencias sobre los triángulos nominales. El recorte del 10 % se limita a la inicialización/ICP de puntos; el refinamiento de superficie usa todas las correspondencias dentro del umbral. Las métricas finales no recortan las distancias de las muestras analizadas.

Para geometrías simétricas, capturas incompletas o una inicialización incorrecta, puedes crear otra comparación con **puntos correspondientes + ICP**. Introduce al menos tres pares XYZ no colineales: el lado del escaneo en las unidades de entrada y el nominal en mm. También puedes conservar las coordenadas de un archivo previamente alineado. La matriz 4×4 transforma el escaneo convertido a mm hacia el sistema del nominal.

El umbral ICP es una distancia de registro/cobertura; la tolerancia es el criterio de desviación que define el usuario. El límite del mapa solo controla sus colores. Son parámetros distintos y quedan guardados.

## Métricas y figuras

- **Hausdorff máximo estimado, mm:** máximo de las dos direcciones. Se muestrean superficies; cada muestra busca el punto más próximo sobre los triángulos del otro modelo, o el vecino más cercano si es una nube. No representa el máximo continuo certificado de toda la superficie.
- **Hausdorff P95, mm:** máximo de los percentiles 95 de ambas direcciones.
- **Chamfer físico, mm²:** media de distancias al cuadrado escaneo→nominal más media nominal→escaneo. Se entrega también una media bidireccional no cuadrática en mm.
- **Desviación absoluta media y RMSE superficial, mm:** dirección escaneo→nominal.
- **Dentro de tolerancia, %:** muestras del escaneo cuya distancia al nominal no supera la tolerancia declarada.
- **Cobertura nominal, %:** muestras nominales a una distancia del escaneo menor o igual al umbral de cobertura. No es una certificación de cobertura completa del escáner.
- **ΔD, mm:** medida de una cota crítica declarada menos su nominal. Se conservan el instrumento/método, todas las repeticiones, la media y la desviación estándar muestral. Con una sola medida, la desviación estándar queda vacía. Sin cotas declaradas, estas métricas quedan sin medir. La dispersión de distancias superficiales se informa por separado.
- **Envolvente XYZ:** dimensiones de la caja de toda la geometría alineada; no se presentan como diámetros, espesores o cotas críticas.
- **Heatmap:** cuatro vistas y escala en mm. Cuando el nominal es cerrado, con orientación consistente y volumen positivo, el signo corresponde a la normal local: azul interior, verde cero y rojo exterior. En otro caso se muestra distancia absoluta. Los colores se saturan en el límite indicado; el CSV conserva las distancias sin saturar.

Se utilizan 20.000 muestras por superficie por defecto, configurables entre 2.000 y 100.000, con semilla fija. En una nube se toman hasta ese número de puntos sin reemplazo. La densidad de una nube afecta especialmente a las distancias nominal→nube. El informe conserva el tipo de entrada, tamaños efectivos, semilla, transformación, parámetros y versiones de bibliotecas.

La precisión comercial de 0,02 mm del Otter no se utiliza como incertidumbre, tolerancia ni resultado medido. Registrar una calibración y confirmar visualmente una alineación tampoco constituye una certificación metrológica.

## Entregables del PDF

| Sección | Archivos y funciones |
| --- | --- |
| 4.1 Digital | Open/closed-loop, tasas acumuladas e incrementales, IR código/CAD, CSV/JSON, figuras PNG/SVG, tiempos y trazas. El conjunto de 60 cumple el rango de 50–100; el de 45 conserva su carácter piloto. IoU necesita STEP independiente y activación explícita. |
| 4.2 Manufactura | `manufacturabilidad.csv` con porcentaje watertight, cobertura de STL y DangEL. Si se aporta fotografía, `comparacion-fotografica.png` muestra render y pieza; el ZIP de campaña compone matrices de varias piezas. |
| 4.3 Metrología | `tabla_metrologica.csv`, `cotas_criticas.csv`, `mapa-desviacion.png`, composiciones de hasta cuatro comparaciones por figura, PLY alineado con colores, `distancias.csv`, transformación, informe HTML autónomo y JSON. |
| Trazabilidad | Escaneo original, nominal usado y sus hashes; foto original si existe, configuración, revisión y manifiesto SHA-256 de la exportación. |

El CSV conserva todas las comparaciones, incluyendo estado, confirmación y calibración. Las figuras se componen con los cálculos terminados y rotulan si falta revisar la alineación. Para el artículo selecciona las piezas y réplicas del protocolo experimental real. El programa no crea impresiones, fotos, escaneos o medidas que no hayas aportado.

## Campañas manuales y resultados externos

Las campañas manuales ahora actualizan archivos visibles al terminar cada trabajo y generan figuras al cerrar la campaña. Usan carpetas `Campana-<id>`; los lotes históricos conservan `L45-<id>` y sus rutas. Los manifiestos informan el conjunto y número real de prompts/ejecuciones. **Actualizar archivos locales** permite reconstruir entregables de campañas anteriores usando SQLite, sin ejecutar CAD ni consultar IA. La plantilla `mediciones_fisicas.csv` ya rellenada por el usuario se conserva; las mediciones nuevas se exportan en `tabla_metrologica.csv`.

En **Métricas → Comparar con resultados de otro método** puedes descargar una plantilla JSON de la campaña. Registra fuente, condiciones y resultados booleanos por caso/repetición. Ciel verifica que el hash del conjunto, los casos, la estrategia y las repeticiones coincidan; rechaza valores pendientes, duplicados o CAD exportable con ejecución fallida. Los archivos se conservan con hash y se incluyen en la tabla Digital Metrics y en datos/trazas.

Las cifras bibliográficas incluidas siguen siendo contexto no pareado. Las filas de ensayos externos aportados se distinguen de la literatura y de las ejecuciones propias. No se deduce Compile Rate de IR ni se presenta una ejecución externa como reproducida por Ciel.

## Fuentes técnicas

- [Creality: formatos del CR-Scan Otter, OBJ/STL/PLY](https://devstore.creality.com/blogs/buying-guides/creality-pika-vs-cr-scan-otter).
- [Equipo indicado por el usuario](https://digitalz3d.com/producto/escaner-3d-creality-cr-scan-otter/).
- [Open3D: ICP y necesidad de una alineación inicial](https://www.open3d.org/docs/latest/tutorial/pipelines/icp_registration.html).
- Implementación local: NumPy/SciPy para el registro rígido y Trimesh/Rtree para proximidad a triángulos; no requiere instalar Open3D o CloudCompare.
