# Código completo del programa nativo y su interfaz web

Copia **toda esta carpeta `edicion-libre/`** para trabajar con la edición Windows. El código está en `programa/`, la interfaz React en `programa/interfaz/` y los scripts de preparación y dependencias en `nativo/`. Sigue [Ejecutar desde el código](nativo/README.md#ejecutar-desde-el-código) para compilar la interfaz y arrancar en Windows.

La entrega actual es **0.8.0**. Para instalarla directamente utiliza [Agente-Ciel-Nativo-0.8.0-Setup.exe](entregas/0.8.0/Agente-Ciel-Nativo-0.8.0-Setup.exe). Las secciones de versiones anteriores que siguen conservan la documentación histórica; el inicio actual de campañas es manual.

# Novedades nativas 0.8.0

Cotas automáticas del escaneo (diámetros y separaciones entre planos), planes por modelo, perfiles reutilizables y Hausdorff discreto con todos los puntos. El estudio principal utiliza los **45 prompts aprobados**; los 60 históricos se conservan. Descarga el [instalador 0.8.0](entregas/0.8.0/Agente-Ciel-Nativo-0.8.0-Setup.exe), consulta [la guía](METROLOGIA_0.8.0.md) y [la validación](VALIDACION_0.8.0.md).

# Novedades nativas 0.7.0

Comparación de piezas impresas manualmente y escaneadas con CR-Scan Otter, entregables físicos y exportaciones completas de campañas manuales. Consulta [la guía de metrología](METROLOGIA_0.7.0.md) y [las instrucciones de Windows](nativo/README.md).

La versión nativa **0.6.0** incorpora historial, variantes y exportación legible compatible con resultados anteriores. Véanse `nativo/README.md` y `VALIDACION_0.6.0.md`.

> Actualización nativa 0.5.1: detección de todos los modelos instalados en Ollama e inicio manual. En Campañas puedes elegir prompts, modelos y librerías antes de calcular, guardar e iniciar. Consulta [la guía nativa](nativo/README.md).

# Agente Ciel para Windows

## Código y versiones en GitHub

Esta carpeta contiene el programa libre completo y tiene un versionado independiente de la aplicación de pago. La versión nativa actual figura en [VERSION](VERSION); sus cambios están en [CHANGELOG.md](CHANGELOG.md) y las comprobaciones de publicación en [VALIDACION_0.5.0.md](VALIDACION_0.5.0.md). Las etiquetas usan `libre-v<versión>`.

Descarga el [instalador nativo 0.5.0](entregas/0.5.0/Agente-Ciel-Nativo-0.5.0-Setup.exe) desde la vista del archivo en GitHub con **Download raw file**. Los [SHA-256](entregas/0.5.0/SHA256SUMS.txt), el paquete y sus metadatos se conservan junto al instalador. El código está en [programa/](programa/), el instalador nativo en [nativo/](nativo/) y el instalador Docker histórico en [instalador/](instalador/). Los pesos de modelos, registros de instalación y resultados locales se crean fuera del control de versiones.

Para reconstruir el instalador nativo desde Linux, con Node.js, Python y Docker:

```bash
npm --prefix edicion-libre/programa/interfaz ci
npm --prefix edicion-libre/programa/interfaz run construir
docker build -t ciel-libre-compilador:nsis -f edicion-libre/instalador/Dockerfile.compilador edicion-libre/instalador
python edicion-libre/construir_nativo.py
```

El instalador reconstruido se genera en `dist-nativo/`. La compilación no ejecuta modelos ni el benchmark. Las instrucciones de instalación y sus límites de validación están en [nativo/README.md](nativo/README.md).

## Edición nativa actual: 0.5.0

Para el equipo sin virtualización utiliza `dist-nativo/Agente-Ciel-Nativo-0.5.0-Setup.exe`. Esta edición llama al Ollama de Windows ya instalado, ejecuta CadQuery, build123d y FreeCAD de forma nativa y conserva las **1.350 ejecuciones** por protocolo. Guarda SQLite y CSV locales. Usa Gemma **Q8_0** instalado por el usuario. El protocolo v2 elimina el tope fijo de salida y amplía el contexto según el modelo. Una instalación 0.4.2 conserva su campaña anterior e inicia otra campaña v2 separada. Consulta [las instrucciones nativas](nativo/README.md).

El instalador está compilado; la aplicación y el benchmark de esta versión no se ejecutaron en Ubuntu. La comprobación real queda pendiente en Windows.

## Edición histórica 0.3.0 con Docker

Edición independiente en `edicion-libre/`. La versión **0.3.0** utiliza **Docker Desktop y Ollama para Windows ya instalados por el usuario**. El instalador se construye en Linux; descarga los cinco modelos y construye los contenedores al ejecutarse en Windows. El instalador y el programa arrancan desde PowerShell, sin instalar Ubuntu ni ejecutar WSL.

## Archivo que debes llevar

`dist/Agente-Ciel-Libre-0.3.0-Setup.exe`

Antes de ejecutarlo, abre **Docker Desktop** y **Ollama para Windows**. En Docker Desktop selecciona **Linux containers** y el motor **Hyper-V**, con **Use the WSL 2 based engine** desmarcado en **Settings → General**. Hyper-V necesita Windows Pro, Enterprise o Education, virtualización habilitada en BIOS/UEFI y una instalación de Docker Desktop que admita ese motor. Tener Docker instalado no elimina estos requisitos. Consulta [Docker Desktop para Windows](https://docs.docker.com/desktop/setup/install/windows-install/) y [sus ajustes](https://docs.docker.com/desktop/settings-and-maintenance/settings/).

El instalador incluye el código y la preparación en PowerShell. Python, Node, PostgreSQL, Redis y los motores CAD se instalan en contenedores; no se requieren instalaciones individuales en Windows. La preparación aparece en una ventana visible y conserva un registro completo. Al terminar abre la aplicación y crea el acceso directo **Agente Ciel Libre**. Una descarga interrumpida se reanuda abriendo ese acceso directo; un error queda en **Diagnóstico** y en `%LOCALAPPDATA%\AgenteCielLibre\ultimo-error.txt`.

Los instaladores 0.1.0 y 0.2.0 corresponden al entorno anterior con WSL. Sus archivos se conservan como entregas históricas; usa el **0.3.0** para Docker Desktop y Ollama Windows. Los datos de una distribución WSL anterior no se migran automáticamente al motor Hyper-V.

## El lote incluido arranca solo

Ya están incluidos los 45 prompts de `45_prompts_Agente_Ciel.md`: 15 B, 15 M y 15 C. La preparación en Windows crea una única campaña automática de **1.350 ejecuciones** (45 × 5 modelos × 3 motores × 2 estrategias). Abrir la app o reiniciar el trabajador recupera esa campaña; no crea otro lote ni repite los casos terminados. La app se registra para abrirse al iniciar sesión en Windows, continuando después de un reinicio.

Un solo trabajador procesa, para cada modelo y motor, los 45 Open-loop y los 45 Closed-loop. El límite es de 4.050 intentos del benchmark. Una interrupción operativa antes de guardar la respuesta puede requerir repetir una llamada local; se registra y no se confunde con una nueva iteración de corrección. Si la respuesta ya está en la base de datos, se vuelve a ejecutar su código sin pedir otra respuesta.

Los problemas temporales de Ollama, CAD o guardado se reintentan con espera creciente entre 10 y 300 segundos. Un script o CAD inválido usa las correcciones permitidas: uno en Open-loop, hasta cinco en Closed-loop. Si los agota, se registra como fallo y se avanza al siguiente prompt. Esto mantiene las tasas de éxito y fallo del experimento. Los fallos permanentes de hardware, disco lleno o cambios de identidad no pueden repararse mágicamente: quedan visibles mientras espera recuperación. Pausar o cancelar desde la app se respeta.

Las descripciones originales se conservan literalmente con sus hashes. La instrucción de sistema se adapta explícitamente a cada motor: `resultado` es la variable del sandbox y el sandbox realiza las exportaciones; no se pide al modelo escribir `output.stl`. El sistema completo de cada condición queda congelado en sus trazas y es igual para Open-loop y Closed-loop del mismo motor.

## Carpetas de resultados en Windows

Se guardan automáticamente en **Documentos\CielLibre\Resultados**, también accesible desde **Inicio → Agente Ciel Libre → Resultados**. Puede ser la carpeta Documentos de OneDrive si Windows la redirige allí.

```text
Resultados/
  L45-<identificador de campaña>/
    progreso.json
    campana.json
    ejecuciones.csv
    metricas.csv
    metricas.json
    tabla_digital.csv
    protocolo/                 # Markdown original, prompts JSON y hashes
    figuras/                   # SVG y PNG finales
    L01_Qwen_3.5_0.8B_Q8_0/
      cadquery/
        open-loop/
          01_basico/
            B01/
              prompt.txt
              caso.json
              resultado.json
              metricas_digitales.json
              intentos/01/     # código, respuesta, solicitud, errores y tiempos
              archivos/        # STEP, STL y código final cuando sean válidos
        closed-loop/
      build123d/
      freecad/
    L02_.../
    L03_.../
    L04_.../
    L05_.../
```

La base de datos y sus intentos son el checkpoint autoritativo; los archivos visibles se escriben mediante reemplazo atómico. Un prompt fallido también tiene carpeta y diagnóstico. Al finalizar se generan figuras por nivel de dificultad y para todo el conjunto. Desde la pestaña **Métricas** se pueden descargar además la tabla, figuras y un ZIP de trazas y CAD. Las actualizaciones del instalador reutilizan la campaña y los modelos; no reinician una campaña terminada.

## Métricas del PDF, etapa digital

Se implementa el alcance de generación de `Requisitos_Resultados-CADLLMIA.pdf`: Compile Rate y sus incrementos por intento, Invalidity Ratio de código y de CAD exportable, éxito CAD, tiempos por intento, tokens y trazabilidad de scripts/artefactos. La figura utiliza Matplotlib y distingue pendientes, bloqueos y resultados finales. Tiempo total es tiempo transcurrido e incluye interrupciones; las latencias de IA/CAD se informan aparte. IoU volumétrico solo se calcula con STEP independiente y el indicador **usar_referencias** activado. Sin referencias queda ausente, no vale cero. También se conserva el análisis digital de STL (watertight y DangEL).

Los 45 casos forman un **piloto**, como dice el Markdown del usuario: el PDF propone 50–100 para la campaña principal. Los 60 casos originales permanecen congelados y separados. No se producen medidas físicas de impresión, escáner, Hausdorff físico ni errores dimensionales físicos.

La tabla exportada incluye dos filas de contexto bibliográfico obtenidas de la [tabla 1 de CAD-Coder, NeurIPS 2025](https://papers.neurips.cc/paper_files/paper/2025/file/564a224e88f2490f3c1deaae877d37e3-Paper-Conference.pdf). Ese estudio usa otro conjunto y no da Compile Rate ni dificultades equivalentes a este lote: esos campos quedan vacíos y la comparación se marca como no directa. No se infiere Compile Rate a partir de su IR. La fuente, página, tabla y hash del PDF están en `datos/literatura_digital_v1.json`.

## Funciones y modelos

Solo hay dos estrategias: **Open-loop**, una generación; y **Closed-loop**, una generación inicial y hasta cuatro correcciones, con parada en el primer CAD válido y exportable. El backend también rechaza Quality Loop, Best-of-N, revisores y proveedores externos. Se conservan CadQuery, build123d, FreeCAD, visor 3D, exportaciones, historial, los 60 casos congelados, campañas y métricas digitales. Validez técnica y fidelidad geométrica siguen siendo resultados diferentes.

| Modelo | Cuantización | Perfil |
| --- | --- | --- |
| Qwen 3.5 0.8B | Q8_0 | L01 |
| Qwen 3.5 2B | Q8_0 | L02 |
| Gemma 3 4B IT | Q5_K_M | L03 |
| Ministral 3 3B Instruct | Q6_K | L04 |
| SmolLM3 3B | Q6_K | L05 |

Los cinco modelos se descargan sin pedir cuentas ni claves. Las cuantizaciones solicitadas se importan desde GGUF fijados por SHA-256; no se sustituyen por la etiqueta `latest` ni por otra cuantización. Las fuentes, revisiones, tamaños, plantillas y licencias están en `programa/datos/modelos_libres/modelos.json`. Los pesos suman aproximadamente 11 GB decimales, además de las dependencias y motores CAD.

Gemma tiene sus propias [condiciones de uso](https://ai.google.dev/gemma/terms). Los otros cuatro modelos usan Apache 2.0. La plantilla de SmolLM3 se adapta de la del autor para conversación de texto en modo `/no_think`; se omite la fecha dinámica y no se habilitan herramientas. Las plantillas de Qwen, Gemma y Ministral provienen del catálogo Ollama. La instalación comprueba cada archivo y conserva el digest de cada modelo importado.

## Requisitos del equipo Windows

- Windows x64 con CPU Intel/AMD, versión compatible con Docker Desktop, edición Pro, Enterprise o Education para Hyper-V.
- Virtualización de hardware y Hyper-V habilitados; Docker Desktop iniciado en modo Linux containers y sin el motor WSL 2.
- Ollama para Windows instalado, actualizado y abierto en el puerto 11434.
- 16 GB de RAM como mínimo; recomendados 32 GB.
- 60 GB libres para la instalación inicial, con espacio adicional para campañas y archivos.
- Al menos 6 GB de RAM asignados a Docker Desktop; recomendados 8 GB.
- Internet durante la preparación inicial y acceso de Docker a las carpetas del programa y Documentos.

Ollama Windows usa CPU o una GPU compatible con su controlador; la inferencia ocurre en Windows. Los modelos se cargan de uno en uno y se descargan de memoria al acabar cada solicitud. Los motores CAD usan la memoria y CPU asignadas a Docker Desktop. Con poca memoria disponible una inferencia puede fallar y quedará un diagnóstico. El instalador no cambia la BIOS, el motor de Docker ni la ubicación elegida para los modelos de Ollama.

Tras una preparación completa, el uso normal es local. Cerrar la ventana deja los servicios en segundo plano; **Detener servicios**, en el menú Inicio, detiene los contenedores de esta edición. Docker Desktop y Ollama siguen disponibles para tus otros programas. Para continuar tras iniciar sesión, activa también el inicio automático de Docker Desktop y Ollama; si aún no están listos, abre Agente Ciel otra vez.

## Aislamiento y archivos

El proyecto Compose se llama **agente-ciel-libre-windows**. Docker Desktop ejecuta la aplicación, la base de datos, la cola, el supervisor, el evaluador y los tres motores CAD. El supervisor ejecuta cada código CAD en un contenedor temporal sin red, con sistema de archivos de solo lectura y límites de recursos.

La interfaz abre `http://127.0.0.1:8010` en el navegador. PowerShell consulta Ollama en `http://127.0.0.1:11434`; los contenedores acceden mediante `http://host.docker.internal:11434`, usando el DNS de Docker Desktop. Antes de iniciar la campaña se comprueban los cinco modelos desde el contenedor de la aplicación. Los servicios no reciben claves de pago y el proveedor solo permite L01–L05.

El programa y los registros quedan en `%LOCALAPPDATA%\AgenteCielLibre`; los modelos, en el almacén de tu Ollama Windows (normalmente `%USERPROFILE%\.ollama\models`, o la ruta definida por `OLLAMA_MODELS`). La base de datos y los artefactos originales quedan en los volúmenes Docker; las copias organizadas, en Documentos\CielLibre\Resultados. El desinstalador conserva los volúmenes, los modelos, el registro de modelos y los resultados.

Los GGUF, plantillas y licencias se verifican con los hashes de `programa/datos/modelos_libres/modelos.json`. Si una descarga cambia, no se importa. La preparación usa el CLI `ollama.exe` de Windows y crea `programa/modelos_instalados.json`, comprobando cuantización y digest. Después elimina la copia de descarga del GGUF para no duplicar los 11 GB de pesos. Las dependencias de contenedores siguen los Dockerfiles y archivos de dependencias del proyecto.

## Conexión de Docker a Ollama Windows

Si Ollama responde en Windows pero falla la comprobación desde Docker, configura **OLLAMA_HOST** como variable de usuario con el valor **0.0.0.0:11434**, sal de Ollama desde su icono de la bandeja y vuelve a abrirlo. Permite la conexión privada de Docker en el firewall; este ajuste permite escuchar fuera de localhost, por lo que el firewall debe restringir el acceso al equipo. No se necesita `OLLAMA_ORIGINS`: las solicitudes salen del backend, no del navegador. Sigue la [configuración oficial de Ollama Windows](https://docs.ollama.com/faq#setting-environment-variables-on-windows).

Si Docker muestra un error de montaje, comparte la carpeta `%LOCALAPPDATA%\AgenteCielLibre` y la carpeta Documentos (incluida la ruta de OneDrive si corresponde) en **Settings → Resources → File sharing**. El instalador no modifica automáticamente los ajustes globales de Docker ni Ollama.

## Ejecutar desde el código sin instalador

Con Docker Desktop en Hyper-V y Ollama Windows abiertos, desde PowerShell en la raíz del repositorio:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\edicion-libre\instalador\preparar-windows.ps1 -Modo Preparar
```

El script encuentra `edicion-libre/programa`, prepara los modelos, construye las imágenes y abre la interfaz. Para detener sus contenedores usa el mismo comando con `-Modo Detener`.

## Reconstruir el instalador

Desde la raíz del repositorio, con Python 3 y Docker disponibles en el equipo de desarrollo:

```bash
python edicion-libre/construir_instalador.py
```

Este comando empaqueta el código y compila NSIS en un contenedor temporal. No ejecuta el programa, no habilita WSL ni descarga pesos. Genera el `.exe`, `programa.zip`, `paquete.json` y `SHA256SUMS.txt` en `dist/`. El código original de pago no forma parte del instalador libre.

## Comprobaciones y límite de la entrega

En 0.3.0 se compilaron el frontend, las seis imágenes Docker y el instalador NSIS. Las 19 pruebas de la aplicación pasaron también en la imagen nueva: cinco modelos, límites de uno/cinco intentos, feedback, rechazo de Quality/Best-of-N/proveedores externos, identidad, reanudación, matriz de 1.350 celdas, checkpoint, carpetas y exportación de figuras/ZIP. No descargan pesos ni llaman a proveedores reales. La revisión visual de temas y tamaños pertenece a la edición anterior; este cambio no modifica el diseño de la interfaz.

Para 0.3.0 se añaden pruebas PowerShell con archivos temporales y respuestas simuladas: aceptación del motor Linux de Docker Desktop, rechazo de WSL y Windows containers, errores Unicode completos, argumentos con espacios, reanudación, rechazo de pesos corruptos y checkpoint de importación de cinco modelos. Se ejecutan sin descargas ni inferencias. Las comprobaciones de la edición anterior se conservan como antecedentes.

Las nueve pruebas PowerShell pasaron en PowerShell 7.4 para Linux. Además, la API arrancó en un proyecto Docker temporal y verificó los cinco modelos usando un servidor Ollama simulado en `host.docker.internal:11434`. CadQuery, build123d y FreeCAD ejecutaron un cubo de 20 mm: el supervisor y el evaluador verificaron STEP/STL y un volumen de 8.000 mm³ para los tres motores. Los contenedores y volúmenes temporales se retiraron después. Detalles en `VALIDACION_0.3.0.md`.

**El instalador 0.3.0 necesita una comprobación final en Windows con Docker Desktop Hyper-V y Ollama Windows reales.** Las pruebas en Linux y PowerShell 7 no sustituyen esa comprobación ni certifican Windows PowerShell 5.1. El ejecutable aún no tiene firma de editor de Windows.

```bash
docker build -t ciel-libre-validacion:local -f edicion-libre/instalador/Dockerfile.validacion edicion-libre
docker run --rm \
  -v "$PWD/edicion-libre/programa:/servicio:ro" \
  -v "$PWD/edicion-libre/pruebas:/pruebas:ro" \
  -e URL_BASE_DATOS=sqlite:// \
  ciel-libre-validacion:local python -m unittest discover -s /pruebas -v
```
