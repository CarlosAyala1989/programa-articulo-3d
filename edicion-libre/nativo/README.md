# Agente Ciel Nativo 0.5.0

## Instalación en Windows

1. Abre Ollama para Windows con los cinco modelos de la tabla.
2. Ejecuta `Agente-Ciel-Nativo-0.5.0-Setup.exe` desde tu sesión normal.
3. Espera la preparación de Python y las bibliotecas CAD. Necesita internet durante esta preparación; los modelos existentes se reutilizan.
4. Se abre `http://127.0.0.1:8020` y comienza el lote automáticamente.

Requisitos: Windows 10 22H2 o Windows 11 x64 Intel/AMD, 16 GB de RAM como mínimo para instalar y 64 GB recomendados para los contextos de este protocolo, más 15 GB libres adicionales al espacio de modelos y resultados. La duración y el tamaño final dependen del código y geometrías producidos. Todo puede estar en C:.

| Modelo | Etiqueta exacta de Ollama | Cuantización |
| --- | --- | --- |
| L01 | `qwen3.5:0.8b-q8_0` | Q8_0 |
| L02 | `qwen3.5:2b-q8_0` | Q8_0 |
| L03 | `gemma3:4b-it-q8_0` | Q8_0 |
| L04 | `hf.co/lmstudio-community/Ministral-3-3B-Instruct-2512-GGUF:Q6_K` | Q6_K |
| L05 | `Impulse2000/smollm3:3b-q6_k` | Q6_K |

## Contexto y salida de la versión 0.5.0

El perfil `ciel-nativo-windows-v2` envía `num_predict=-1` a Ollama: la aplicación no impone un máximo fijo de tokens de salida. L01–L04 usan `num_ctx=98.304` y L05 usa `num_ctx=65.536`, su longitud nativa documentada. La ventana de contexto contiene **entrada y salida juntas**; por ello una entrada de 65.000 tokens deja unos 33.000 tokens para la respuesta en L01–L04, pero casi ninguno en L05. No se promete generación infinita: el modelo puede detenerse, alcanzar su propio límite, agotar memoria o superar el tiempo de espera de seis horas. Gemma 3 4B documenta un límite de salida propio de 8.192 tokens. El motivo de finalización, los tokens efectivos y el perfil se guardan por intento.

El límite de código CAD sube a 1 MiB UTF-8. El equipo de referencia tiene 64 GB de RAM y RTX A1000 de 8 GB; los contextos largos pueden desbordar la VRAM y usar RAM/CPU, reduciendo mucho la velocidad. Se mantiene una sola ejecución a la vez.

Antes de instalar 0.5.0 sobre 0.4.2, cierra la ventana de la aplicación anterior. La nueva versión conserva SQLite, resultados y modelos. El cambio de parámetros crea **una campaña v2 nueva de 1.350 ejecuciones**; la campaña v1 queda en la misma base y sus resultados siguen en su carpeta. Las ejecuciones pendientes de v1 quedan pausadas y no se mezclan con v2. Al reabrir 0.5.0 se recuperan únicamente las pendientes de v2.

## Reparar la ruta de FreeCAD de la versión 0.4.1

El instalador 0.4.2 elige una carpeta que contenga **FreeCAD.exe y python.exe juntos**, en lugar del primer FreeCAD.exe que encuentre. El portable puede incluir un lanzador en su carpeta principal; ese archivo no identifica el directorio de Python. El fijador de runtimes también acepta la carpeta raíz o bin y resuelve la ubicación válida antes de crear su manifiesto.

Ejecuta `Agente-Ciel-Nativo-0.4.2-Setup.exe` sobre la instalación existente, con el mismo usuario, sin borrar carpetas. Reutiliza FreeCAD ya extraído cuando su marcador y ejecutables son válidos. Conserva Python, entornos, modelos, SQLite, resultados y la matriz de 1.350 ejecuciones. Las versiones CAD y el protocolo experimental no cambian. La preparación imprime la ruta bin seleccionada y configura UTF-8 para la salida de Python.

## Reparar el error BCJ2 de la versión 0.4.0

Ejecuta `Agente-Ciel-Nativo-0.4.2-Setup.exe` sobre la instalación existente, desde el mismo usuario de Windows. Conserva la carpeta `%LOCALAPPDATA%\AgenteCielNativo` y no desinstales previamente. La reparación utiliza la descarga de FreeCAD ya verificada y reutiliza los entornos de Python preparados. Los modelos, SQLite, resultados y las 1.350 ejecuciones permanecen en sus carpetas existentes.

La extracción usa `herramientas/7zr.exe`, 7-Zip 26.04 oficial incluido en el instalador, con su hash y licencias. `py7zr` deja de ser una dependencia. El archivo FreeCAD usa BCJ2, un filtro que esa biblioteca no admite. La extracción se realiza en una carpeta temporal y solo se publica al terminar correctamente; un marcador acredita que se completó, por lo que una extracción parcial no se da por instalada. No se instala 7-Zip de forma global.

La comprobación de espacio distingue una instalación nueva (15 GB) de completar una preparación con los tres entornos existentes (3 GB adicionales, más resultados). Si el ZIP portable ya está en `descargas`, su hash se verifica y no se vuelve a descargar.

Fuentes: [limitación BCJ2 de py7zr](https://py7zr.readthedocs.io/en/latest/_modules/py7zr/compressor.html) y [7-Zip oficial](https://www.7-zip.org/download.html).

## Ejecución y recuperación

La matriz se conserva: **45 × 5 × 3 × 2 = 1.350 ejecuciones**. Los motores son CadQuery 2.6.1, build123d 0.13.0 y FreeCAD 1.1.3, con entornos separados. Una ejecución open-loop permite una generación; una closed-loop, hasta cinco. El máximo experimental es 4.050 generaciones. Los reintentos por interrupciones operativas se registran aparte.

Se procesa una ejecución a la vez. Puedes pausar y reanudar en la interfaz. Cerrar la consola de Python detiene los servicios y los procesos CAD. Al abrir el acceso directo se recuperan las ejecuciones pendientes; las terminadas se conservan. La aplicación se abre también al iniciar sesión en Windows.

El controlador, los procesos CAD y la preparación de dependencias rechazan la ejecución fuera de Windows. Esta entrega se preparó mediante edición, inspección estática y compilación del instalador, sin iniciar la aplicación, motores, modelos ni benchmark en Ubuntu. El funcionamiento real de Windows queda pendiente de comprobar en el equipo de destino.

## Archivos locales

- SQLite activo: `%LOCALAPPDATA%\AgenteCielNativo\datos\ciel.sqlite`.
- Resultados: `Documentos\CielLibre\Resultados\L45-<identificador>\`.
- Registros y diagnóstico: `%LOCALAPPDATA%\AgenteCielNativo\registros\` y `ultimo-error.txt`.
- Copia consistente de SQLite: `resultados.sqlite`, cada 50 ejecuciones terminadas y al cierre del lote. La copia incluye la base local completa; el checkpoint activo se guarda después de cada paso.

Cada carpeta de resultados contiene `ejecuciones.csv`, `intentos.csv`, `metricas.csv`, `metricas_detalladas.csv`, `geometria.csv`, `manufacturabilidad.csv`, `mediciones_fisicas.csv`, JSON del progreso/protocolo y, al terminar, las figuras. Cada intento conserva respuesta, código, parámetros, diagnósticos y archivos geométricos generados. Si Excel bloquea un CSV, se escribe una alternativa `*-actualizado-*.csv`; conviene cerrar Excel para mantener los nombres principales actualizados.

## Métricas y requisitos del PDF

Se mantienen Compile Rate acumulado e incremental por intento, IR de código/CAD, tiempos, tokens, diagnósticos, primera compilación/exportación correcta, hash de código/prompt/modelos, DangEL, watertight, topología y geometría BRep. Se añaden duraciones y tasas de tokens reportadas por Ollama, muestreo de CPU/RAM/RSS de Ollama, VRAM reportada por `/api/ps` y memoria pico/tiempos CPU del Job Object CAD. El muestreo incluye otras aplicaciones en la carga global de Windows; la suma RSS puede contar memoria compartida más de una vez. Valores no disponibles quedan vacíos.

IoU y Chamfer digital necesitan STEP de referencia independiente y `usar_referencias` activado explícitamente; las referencias nunca se envían al modelo. El lote automático se crea sin referencias. Manufacturabilidad digital no certifica una impresión física. `mediciones_fisicas.csv` es una plantilla para fotografías, escaneos, ICP, Hausdorff, Chamfer físico, cotas, media/desviación y mapas de calor: requieren datos físicos reales y no se calculan ni inventan a partir de la generación digital. El PDF propone 50–100 prompts; estos 45 se mantienen como piloto por solicitud del usuario. Las comparaciones de literatura están identificadas como no pareadas.

El protocolo actual es `ciel-lote-45-windows-nativo-v2`. Gemma Q8_0 y FreeCAD 1.1.3 se documentan como cambios frente a la edición Docker anterior. Los digest completos de modelos y las versiones efectivas de runtimes se congelan para detectar cambios al reanudar.

## Ejecutar desde el código

Con el repositorio copiado a Windows, abre PowerShell en su raíz:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\edicion-libre\nativo\preparar.ps1
```

Este comando prepara las mismas bibliotecas y arranca la misma aplicación. Ollama y los cinco modelos deben estar disponibles previamente.

## Diagnóstico

Ante un fallo abre `ultimo-error.txt` y el registro de preparación/aplicación. La ventana muestra el mensaje completo. Después de corregir la causa, abre el acceso directo para reanudar. Cambiar modelos o versiones a mitad de campaña necesita un protocolo y una campaña nuevos; conserva previamente los archivos y SQLite existentes.

Fuentes de instalación: [CadQuery](https://cadquery.readthedocs.io/en/stable/installation.html), [build123d](https://build123d.readthedocs.io/en/stable/installation.html), [FreeCAD 1.1.3](https://github.com/FreeCAD/FreeCAD/releases/tag/1.1.3), [Python en Windows](https://docs.python.org/3.11/using/windows.html) y [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).
