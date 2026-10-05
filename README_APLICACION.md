# Agente Ciel · generación CAD y evaluación digital

Aplicación local para convertir descripciones en español en modelos CAD con **CadQuery, build123d y FreeCAD Python API**. Permite generación individual y campañas con **open-loop** (un intento) y **closed-loop** (hasta cinco intentos con diagnóstico y reparación). Incluye el conjunto versionado **CAD-LLMIA-60**: 20 casos básicos, 20 intermedios y 20 complejos. La aplicación calcula únicamente resultados digitales; no gestiona impresión, fotografías, escáneres ni metrología física.

Cada ejecución conserva la solicitud efectiva, respuesta, script, tokens, latencia, fase de fallo, primer éxito de ejecución, primer CAD válido, primer CAD exportable y archivos con SHA-256. Una respuesta de IA se persiste antes de pasar al runtime CAD. Un proceso abortado con desenlace incierto se muestra como incidencia; nunca se reenvía automáticamente una petición cuya facturación o respuesta podría haberse perdido.

## Arranque

1. Crear un archivo de entorno **fuera del repositorio** con `DEEPSEEK_API_KEY=...`, por ejemplo `/tmp/agente-ciel.env`, y limitar sus permisos a `600`.
2. Construir las tres imágenes CAD y los servicios:

   ```text
   docker compose --env-file /tmp/agente-ciel.env --profile imagenes build
   ```

3. Levantar la aplicación:

   ```text
   docker compose --env-file /tmp/agente-ciel.env up -d
   ```

4. Abrir <http://localhost:8000>. El puerto está vinculado a `127.0.0.1`; si se publica en la red universitaria, se requiere autenticación y control de acceso antes de exponerlo.

PostgreSQL y el volumen `artefactos` conservan campañas, intentos y archivos al reiniciar. Redis mantiene la cola. El trabajador recibe la clave DeepSeek; el navegador, evaluador y runtimes CAD no la reciben. El supervisor crea contenedores efímeros sin red, con sistema de archivos de solo lectura y límites de CPU, memoria, procesos y duración. Por tener acceso al socket de Docker, debe ejecutarse solo en un host controlado.

## Modelos y motores

Los modelos pagados habilitados son `deepseek-flash` y `deepseek-v4-pro`, cada uno probado en el piloto con los tres motores. El catálogo local contiene L01–L05 con las cuantizaciones especificadas:

| Perfil | Modelo | Cuantización | Variable de entorno |
|---|---|---|---|
| L01 | Qwen 3.5 0.8B | Q8_0 | `OLLAMA_L01` |
| L02 | Qwen 3.5 2B | Q8_0 | `OLLAMA_L02` |
| L03 | Gemma 3 4B | Q5_K_M | `OLLAMA_L03` |
| L04 | Ministral 3 3B | Q6_K | `OLLAMA_L04` |
| L05 | SmolLM3 3B | Q6_K | `OLLAMA_L05` |

Para activar un perfil local, configurar su etiqueta exacta en el mismo archivo de entorno y `URL_OLLAMA` si Ollama corre en otra máquina. El adaptador consulta `/api/tags` antes de cada generación y exige que la etiqueta exista y reporte la cuantización requerida; guarda digest y modelo informado. No sustituye un perfil por otro ni invoca DeepSeek cuando falla Ollama. El servidor Ollama debe ser alcanzable desde los contenedores por una red privada. **No se han instalado ni probado aún los cinco modelos locales en la máquina universitaria**; su disponibilidad depende de esos pesos y de la configuración de Ollama.

La tarifa de DeepSeek usada para **estimar**, no facturar, es la tarifa pico sin descuento de caché consultada el 2026-10-04. La vista previa de la plantilla `v5-formas-organicas-avanzadas` supone conservadoramente 65.536 tokens de entrada y hasta 131.072 de salida por generación pagada, incluido el razonamiento, para contemplar el programa completo y el historial de fallos. El consumo real puede ser mucho menor. La campaña permite un tope estimado y se pausa antes de una nueva llamada si no dispone de margen; una solicitud que termina en timeout remoto podría tener un cargo desconocido. Los archivos del entorno nunca se copian a imágenes ni se incluyen en exportaciones.

## Detalle y feedback de corrección

Cada intento de closed-loop recibe el objetivo original, el **programa anterior completo** (hasta 90.000 bytes UTF-8), los diagnósticos de todos los intentos fallidos, la fase de fallo y, cuando hay una excepción durante la ejecución, la línea, el fragmento de código y la traza técnica. Se detectan repeticiones del código mediante su AST, ignorando comentarios y formato; si se repite un fallo, la siguiente solicitud pide cambiar la estrategia constructiva. Las orientaciones cubren redondeos incompatibles, sólidos desconectados y errores de API de las versiones realmente instaladas. La firma del error ignora cambios de línea; las orientaciones de loft también evitan perfiles pendientes duplicados. Esto mejora el feedback, pero la IA todavía puede equivocarse: se mantienen cinco generaciones como máximo, sin ocultar ni reemplazar sus respuestas por piezas de respaldo.

La solicitud efectiva y la evidencia del runtime se conservan en `solicitud_modelo` (`mensajes`, `retroalimentacion`, `validacion_cad`, `plantilla`). El historial de la interfaz permite desplegar **Feedback de corrección** para inspeccionar el texto de la solicitud. Una ejecución pausada recupera esa evidencia antes de su próximo intento. Los fallos de proveedor o infraestructura siguen causando bloqueo, en lugar de consumir otro intento geométrico.

Flash y Pro usan razonamiento habilitado con esfuerzo `max` y un límite de 131.072 tokens de salida. Se ejecuta únicamente el contenido final del mensaje; el consumo total informado incluye los tokens de razonamiento. No se envía temperatura porque no tiene efecto en ese modo, según la [API oficial de DeepSeek](https://api-docs.deepseek.com/api/create-chat-completion/). El perfil queda guardado en cada condición e intento. Ollama conserva temperatura 0,2 y hasta 8.000 tokens de salida. El cliente admite hasta 30 minutos de espera de lectura para generaciones largas. Un timeout de lectura bloquea la ejecución y no reenvía automáticamente esa petición. El código ejecutable tiene un límite de 90.000 bytes UTF-8, compatible con su transporte base64 al contenedor, y la respuesta final se conserva hasta 600.000 caracteres. Este cambio puede aumentar duración y consumo por llamada.

El system prompt se mantiene en `aplicacion/prompts_sistema.py`, con instrucciones comunes y contratos específicos de las tres API instaladas. Prioriza silueta orgánica, contornos spline/B-spline, lofts no reglados y barridos con perfiles orientados. Exige integrar relieves en la superficie real y comprobar que los cortes modifiquen el volumen y sean abiertos al exterior. Incluye patrones mínimos de loft verificados en cada runtime; son ejemplos de API, no piezas de respaldo. La IA debe conservar los rasgos al reparar el CAD. Para solicitudes de cabeza clava Chavín se añade una guía de interpretación estilizada con rasgos humanos/felínicos y espiga posterior, basada en [Ministerio de Cultura](https://museos.cultura.pe/sites/default/files/publicaciones/pdf/expoicpp.pdf) y [Museo Larco](https://www.museolarco.org/exposicion/exposicion-permanente/exposicion-en-linea/introduccion/cabezas-clavas-2/). La descripción explícita del usuario tiene prioridad sobre esa guía. Las referencias STEP independientes de evaluación nunca se envían a la IA.

Los tres runtimes exportan un STL nativo con desviación lineal **absoluta de 0,02 mm** y angular **0,05 rad**. El STEP conserva la geometría B-Rep; el STL común del evaluador mantiene su perfil de comparación previamente definido. El visor suaviza normales de curvas y preserva discontinuidades angulares de 30° o más; esto afecta únicamente la iluminación, no las coordenadas ni los archivos. El encuadre inicial adapta la cámara al volumen y al tamaño del visor para mostrar la pieza con mayor claridad.

**La validez CAD y la resolución STL no certifican parecido visual o fidelidad arqueológica.** La parada sigue ocurriendo al obtener el primer CAD válido y exportable. Una réplica exacta necesita una referencia y una evaluación de semejanza apropiada; los rasgos ausentes no se recuperan solo aumentando la cantidad de triángulos. Para no mezclar protocolos, las campañas de las plantillas anteriores conservan sus resultados históricos y deben recrearse como campañas nuevas antes de usar la plantilla v5.

## Conjunto, referencias y campañas

`datos/prompts_60_v1.json` es el conjunto principal; `datos/construir_conjunto.py` documenta sus 60 descripciones, familias y fundamentos de dificultad. Al arrancar, la API lo importa de modo idempotente y rechaza una nueva carga que use su nombre y versión con contenido diferente. Se pueden importar otros conjuntos JSON/CSV, con 50–100 casos para evaluación o menos en desarrollo. El conjunto principal está congelado: el texto y la clasificación no cambian dentro de una campaña.

La interfaz muestra los 60 casos y permite adjuntar a cada uno una **referencia STEP diseñada independientemente**, con procedencia y hash. No se envía al proveedor de IA. Una referencia de un caso ya ensayado no se modifica; para cambiarla se crea otro conjunto/versionado. Una campaña al iniciarse congela los hashes de referencias y de las imágenes CAD, además del conjunto, parámetros y orden aleatorio por bloques. Si cambia una imagen antes de reanudar, debe crearse una campaña nueva.

Para preparar una campaña, seleccionar casos, modelos, motores, modos, repeticiones y semilla; consultar primero la vista previa y luego guardar el borrador. **Guardar el borrador no llama a ninguna IA.** El botón «Iniciar campaña» sí activa la cola. Hay controles de pausa, reanudación, cancelación de pendientes y actualización del tope. Una repetición de 60 casos para Flash y Pro con los tres motores y dos modos programa **720 ejecuciones** y un máximo de **2.160 generaciones**. La vista muestra estados separados para desenlaces científicos, bloqueos, cancelaciones y pendientes.

La parada se produce en el primer CAD válido y exportable. Cada motor produce STEP y STL; FreeCAD entrega además FCStd. Un verificador independiente vuelve a abrir STEP/STL antes de declarar éxito de exportación. Después se genera un STL común desde STEP y se estudian tanto la malla nativa como la común. Un fallo posterior del análisis no consume otro intento de IA ni convierte en fallo un CAD previamente exportado.

## Métricas

- **Compile Rate acumulado hasta el intento k:** ejecuciones evaluables cuyo script terminó sin excepción por primera vez hasta k, dividido entre N evaluable. Un script que corre pero no devuelve un sólido válido sí cuenta como éxito de ejecución.
- **IR-CAD:** ejecuciones evaluables sin CAD válido y exportable, dividido entre N evaluable. No es necesariamente el complemento del Compile Rate.
- **Watertight y DangEL:** se calculan sobre un STL final por ruta. Las tasas de malla informan el número de STL realmente analizados y su cobertura frente a la campaña.
- **IoU B-Rep y Chamfer digital cuadrático bidireccional [mm²]:** solo se calculan con un STEP de referencia independiente. Chamfer usa 8.192 puntos por superficie y una semilla fija. Sin referencia aparece «sin referencia», no cero.
- Los gráficos por iteración usan la propia cohorte closed-loop. El open-loop aparece como condición independiente; las comparaciones con CadQuery se calculan sobre pares de casos evaluables comunes.

Los informes incompletos se rotulan provisionales. Las tasas con denominador cero se representan como no calculables. La interfaz ofrece CSV de métricas y JSON con el manifiesto, las respuestas, scripts, diagnósticos, archivos, topología y comparaciones. El JSON puede incluir respuestas y scripts extensos; se debe custodiar como evidencia de investigación.

## API y pruebas

La interfaz se divide en cinco páginas: **Generar pieza**, **Resultado 3D**, **60 casos**, **Campañas** y **Métricas**. La navegación conserva los campos de generación y de campaña mientras la sesión permanece abierta. El resultado admite un enlace directo `/#/resultado/{id}`; recargarlo recupera la ejecución desde la API. Los botones Atrás y Adelante funcionan con estas rutas. Los temas claro y oscuro siguen disponibles en todas las páginas.

El campo **Nivel de esfuerzo** está separado del modelo y permanece bloqueado mientras no se seleccione uno. Flash y Pro permiten **Bajo (`low`), Alto (`high`) y Máximo (`max`)**, según la [documentación oficial de DeepSeek](https://api-docs.deepseek.com/guides/thinking_mode/). Se propone Máximo para mantener el comportamiento anterior, pero la elección se guarda y se envía como `reasoning_effort` a DeepSeek en todos los intentos y correcciones. La API acepta `esfuerzo_razonamiento` en generaciones y campañas; si un cliente anterior lo omite, usa `max` para DeepSeek. Para Ollama no se aplica este control y la API rechaza un esfuerzo explícito.

Una campaña congela un mismo nivel de esfuerzo para sus modelos DeepSeek, sus condiciones y ejecuciones; los perfiles locales mantienen su configuración propia. El manifiesto JSON exportado conserva esos perfiles. Para comparar niveles distintos se preparan campañas distintas. Las ejecuciones antiguas muestran el esfuerzo de sus trazas si existe; no se atribuye un nivel inventado a resultados sin registro.

Endpoints principales:

| Ruta | Uso |
|---|---|
| `GET /api/opciones` | Motores, modos y modelos configurados |
| `GET /api/conjuntos` y `GET /api/conjuntos/{id}` | Conjuntos y 60 casos |
| `PUT /api/casos/{id}/referencia` | STEP independiente y procedencia |
| `POST /api/ejecuciones` | Generación individual |
| `GET /api/ejecuciones/{id}` | Intentos, archivos y resultados digitales |
| `POST /api/campanas/previsualizar` | Tamaño y costo estimado de la matriz |
| `POST /api/campanas` | Borrador de campaña |
| `POST /api/campanas/{id}/iniciar`, `/pausar`, `/cancelar` | Control de cola |
| `PATCH /api/campanas/{id}/presupuesto` | Ajustar el tope estimado |
| `GET /api/campanas/{id}/metricas` | Tasas con denominadores y comparaciones |
| `GET /api/campanas/{id}/metricas.csv` y `/datos.json` | Exportaciones |

Pruebas del protocolo y bucles:

```text
docker run --rm --network agente-ciel_default -v "$PWD/pruebas:/servicio/pruebas:ro" -v "$PWD/datos:/servicio/datos:ro" -v "$PWD/aplicacion:/servicio/aplicacion:ro" -v "$PWD/motores:/servicio/motores:ro" ciel-aplicacion:piloto python -m unittest discover -s pruebas -v
```

Pruebas geométricas del evaluador:

```text
docker run --rm -v "$PWD/pruebas:/servicio/pruebas:ro" -v "$PWD/evaluador:/servicio/evaluador:ro" ciel-evaluador:piloto python -m unittest discover -s pruebas -p test_evaluador.py -v
```

El piloto real B01 ejecutó 12 condiciones (Flash/Pro × tres motores × dos modos); las 12 generaron STEP/STL/FCStd cuando correspondía, se analizaron ambas rutas STL y se compararon con una referencia manual independiente. Es una prueba de integración de un caso básico, **no** un resultado estadístico de la matriz de 60 casos. La campaña principal de 720 ejecuciones permanece como borrador hasta que se inicie expresamente desde la interfaz o API.
