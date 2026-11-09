# Validación de Agente Ciel Nativo 0.8.0

Fecha: 8 de noviembre de 2026. La instalación 0.7.0 funciona en Windows según la confirmación del usuario. Esta actualización se construye y valida desde Linux; la ejecución del instalador 0.8.0 en Windows no se ha reproducido en este entorno.

## Comprobaciones funcionales

- 68 pruebas unitarias correctas: las 53 anteriores y 15 regresiones de cotas, perfiles, planes, Hausdorff, compatibilidad v1 y respaldo SQLite. IA y CAD generativo se simulan; no se llaman proveedores de pago.
- STL público `plate_holes.STL`, repositorio Trimesh, commit `fb7fc0b374ba72a3cce5bfb553ad90c805ce0b8e`, licencia MIT. SHA-256 original `318f92206dd20b2cede5b70eb5e686d3627c6b157b91e9ed383314329dcff209`. Fuente y licencia conservadas en `pruebas/datos/placa_publica/`.
- Copia centrada y escalada a 1:4: 50,8 × 76,2 × 3,175 mm. Se detectan seis paredes cilíndricas y tres separaciones entre planos.
- Cuatro controles reproducibles: malla idéntica, contracción uniforme del 1 %, espesor +0,2 mm y diámetro +0,2 mm. 36 cotas verificadas; error máximo respecto al cambio impuesto 0,0001481 mm, por debajo del umbral de prueba de 0,003 mm. Esta cifra mide corrección del software en controles sintéticos; no describe la precisión del Otter.
- Nube cilíndrica analítica con ruido de 0,003 mm y diámetro +0,2 mm; recuperación de ΔD dentro de 0,002 mm. Media pared o un único plano se informan sin medida. Regresión de dos diámetros coaxiales vecinos, incluso si se selecciona solo el menor.
- Hausdorff discreto exhaustivo contrastado con `scipy.spatial.distance.directed_hausdorff`, conservando puntos atípicos, incluido un vértice aislado sin triángulos en un PLY. Se distinguen el máximo discreto, el máximo de superficie muestreada y la dispersión entre cotas.
- Los planes modificados o asociados a otro hash se rechazan. Cambiar perfil o selección crea versiones nuevas sin cambiar la configuración de comparaciones anteriores. Fechas, calibraciones y medidas no se reutilizan desde un perfil.

- Integración HTTP real de los dos servicios con SQLite aislado: alta de perfil/plan, carga PLY, PCA/ICP de placa contraída y rotada/trasladada, nueve cotas correctas, confirmación y ZIP con 19 archivos cuyos hashes coinciden. dH discreto 0,473345 mm, máximo superficial muestreado 0,470449 mm y ΔD medio −0,157132 mm. Son controles sintéticos.
- Flujo de carga en navegador: archivo PLY del control de espesor +0,2 mm, reutilización de perfil/plan y comparación final con nueve cotas medidas.

- Interfaz revisada en claro/oscuro, escritorio 1440×1000 y móvil 390×844. Ancho del documento igual al viewport en los cuatro estados. Las cotas muestran código y ubicación nominal en formulario y resultados para distinguir agujeros iguales. La corrección de claridad solicitada por revisión independiente quedó resuelta.
- Instalador NSIS generado, 57 archivos del paquete comprobados byte a byte contra el código/bundle actuales, tres pruebas de entrega correctas y entrega 0.7.0 verificada sin cambios.

## Reproducción

Desde la raíz del repositorio, con la imagen local de validación:

```bash
docker run --rm --network none -v "$PWD/edicion-libre:/servicio:ro" -w /servicio/programa -e PYTHONPATH=/servicio/programa -e URL_BASE_DATOS=sqlite:// -e DIRECTORIO_ARTEFACTOS=/tmp/artefactos -e DIRECTORIO_RESULTADOS=/tmp/resultados -e OPENBLAS_NUM_THREADS=1 ciel-metrologia-validacion:local python -m unittest discover -s /servicio/pruebas -v
```

`herramientas/validar_metrologia_publica.py` genera los cuatro controles, originales transformados, configuración y plan, JSON/CSV, PNG/PLY y un informe HTML. Requiere las dependencias bloqueadas de `nativo/requirements-metrologia.txt`, `PYTHONPATH=programa` y una carpeta de salida nueva. Los modelos son públicos y el ensayo funciona sin red después de descargados.

## Alcance

No se han impreso ni escaneado piezas durante estas pruebas. Los datos de desarrollo se guardaron en una base aislada, sin añadirlos a campañas de investigación. La selección de cotas críticas, calibración del Otter, parámetros de fabricación, fotografías y escaneos reales siguen siendo evidencia del experimento.

La detección automática cubre planos paralelos y cilindros completos. Para otras geometrías siguen disponibles las mediciones complementarias; no se afirma cobertura universal de cotas. Consulte `METROLOGIA_0.8.0.md` para los límites de asociación, cobertura e interpretación del Hausdorff discreto.
