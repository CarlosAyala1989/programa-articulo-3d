# Agente Ciel · generación CAD y evaluación digital

Aplicación local para convertir descripciones en español en modelos CAD con **CadQuery, build123d y FreeCAD Python API**. La interfaz permite generación individual y campañas con **open-loop** (un intento) y **closed-loop** (hasta cinco intentos con diagnóstico y reparación). El código de **Quality Loop experimental** y sus informes se conservan, con la opción oculta en el selector de estrategias.

Incluye los conjuntos versionados **CAD-LLMIA-45**, compartido con la edición libre (15 casos básicos, 15 intermedios y 15 complejos), y **CAD-LLMIA-60**, histórico (20 casos por nivel). Ambos se cargan congelados al arrancar, sin duplicarse tras reiniciar. En **Prompts CAD** y **Campañas**, el selector permite elegir el conjunto; los 45 prompts aparecen inicialmente. Para campañas piloto, **Seleccionar todos los prompts** marca todos los casos del conjunto activo y **Quitar selección** los desmarca. La campaña principal conserva sus 60 casos y condiciones históricas. La aplicación calcula únicamente resultados digitales; no gestiona impresión, fotografías, escáneres ni metrología física.

Cada ejecución conserva la solicitud efectiva, respuesta, script, tokens, latencia, fase de fallo, primer éxito de ejecución, primer CAD válido, primer CAD exportable y archivos con SHA-256. Una respuesta de IA se persiste antes de pasar al runtime CAD. Un proceso abortado con desenlace incierto se muestra como incidencia; nunca se reenvía automáticamente una petición cuya facturación o respuesta podría haberse perdido.

## Arranque

1. Crear un archivo de entorno **fuera del repositorio**, por ejemplo `/tmp/agente-ciel.env`, y limitar sus permisos a `600`. Añadir `DEEPSEEK_API_KEY=...` si se usará DeepSeek, o configurar los proveedores de suscripción descritos abajo.
2. Construir las tres imágenes CAD y los servicios:

   ```text
   docker compose --env-file /tmp/agente-ciel.env --profile imagenes build
   ```

3. Levantar la aplicación:

   ```text
   docker compose --env-file /tmp/agente-ciel.env up -d
   ```

4. Abrir <http://localhost:8000>. El puerto está vinculado a `127.0.0.1`; si se publica en la red universitaria, se requiere autenticación y control de acceso antes de exponerlo.

PostgreSQL y el volumen `artefactos` conservan campañas, intentos y archivos al reiniciar. Redis mantiene la cola. Las claves DeepSeek y NVIDIA se leen de variables de entorno; NVIDIA solo se inyecta en API y trabajador, y ninguna clave se guarda en PostgreSQL, artefactos, logs, imágenes o navegador. El evaluador y los runtimes CAD no reciben credenciales. El supervisor crea contenedores efímeros sin red, con sistema de archivos de solo lectura y límites de CPU, memoria, procesos y duración. Por tener acceso al socket de Docker, debe ejecutarse solo en un host controlado.

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

La tarifa de DeepSeek usada para **estimar**, no facturar, es la tarifa pico sin descuento de caché consultada el 2026-10-04. La vista previa de las campañas nuevas supone conservadoramente 65.536 tokens de entrada y hasta 393.216 de salida por generación pagada, incluido el razonamiento, para contemplar el programa completo y el historial de fallos. El consumo real puede ser mucho menor. El límite de salida queda congelado al crear cada campaña; las campañas anteriores conservan sus 131.072 tokens. La campaña permite un tope estimado y se pausa antes de una nueva llamada si no dispone de margen, usando su límite congelado; una solicitud que termina en timeout remoto podría tener un cargo desconocido. Los generadores NVIDIA comprobados aparecen en el selector solo con `NVIDIA_API_KEY` presente. Los archivos del entorno nunca se copian a imágenes ni se incluyen en exportaciones.

## Detalle y feedback de corrección

Cada intento de closed-loop recibe el objetivo original, el **programa anterior completo**, sin recorte por tamaño de texto, los diagnósticos de todos los intentos fallidos, la fase de fallo y, cuando hay una excepción durante la ejecución, la línea, el fragmento de código y la traza técnica. Se detectan repeticiones del código mediante su AST, ignorando comentarios y formato; si se repite un fallo, la siguiente solicitud pide cambiar la estrategia constructiva. Las orientaciones cubren redondeos incompatibles, sólidos desconectados y errores de API de las versiones realmente instaladas. La firma del error ignora cambios de línea; las orientaciones de loft también evitan perfiles pendientes duplicados. Esto mejora el feedback, pero la IA todavía puede equivocarse: se mantienen cinco generaciones como máximo, sin ocultar ni reemplazar sus respuestas por piezas de respaldo.

La solicitud efectiva y la evidencia del runtime se conservan en `solicitud_modelo` (`mensajes`, `retroalimentacion`, `validacion_cad`, `plantilla`). El historial de la interfaz permite desplegar **Feedback de corrección** para inspeccionar el texto de la solicitud. Una ejecución pausada recupera esa evidencia antes de su próximo intento. Los fallos de proveedor o infraestructura siguen causando bloqueo, en lugar de consumir otro intento geométrico.

Flash y Pro usan razonamiento habilitado con esfuerzo seleccionable (`low`, `high` o `max`; predeterminado `max`) y un máximo de **393.216 tokens (384 K)** de salida por solicitud nueva, confirmado en los metadatos `/models` de la API y en la [documentación oficial de modelos](https://api-docs.deepseek.com/api/list-models/). Es un techo, no una cantidad de tokens garantizada. Se ejecuta únicamente el contenido final del mensaje; el consumo total informado incluye los tokens de razonamiento. No se envía temperatura porque no tiene efecto en ese modo, según la [API oficial de DeepSeek](https://api-docs.deepseek.com/api/create-chat-completion/). El perfil queda guardado en cada condición e intento. Ollama conserva temperatura 0,2 y usa `num_predict=-1` (sin tope de generación añadido por la aplicación); su contexto depende del modelo y del servidor local. El cliente admite hasta tres horas de espera de lectura para generaciones extensas. Un timeout de lectura bloquea la ejecución y no reenvía automáticamente esa petición. El código se entrega íntegro por la entrada estándar al contenedor CAD; ya no viaja en una variable de entorno ni tiene el antiguo tope de 90.000 bytes. La respuesta final del proveedor se guarda completa para conservar la trazabilidad. El mayor techo puede aumentar duración, almacenamiento y consumo por llamada.

El system prompt se mantiene en `aplicacion/prompts_sistema.py`, con instrucciones comunes y contratos específicos de las tres API instaladas. Prioriza silueta orgánica, contornos spline/B-spline, lofts no reglados y barridos con perfiles orientados. Exige integrar relieves en la superficie real y comprobar que los cortes modifiquen el volumen y sean abiertos al exterior. Incluye patrones mínimos de loft verificados en cada runtime; son ejemplos de API, no piezas de respaldo. La IA debe conservar los rasgos al reparar el CAD. Para solicitudes de cabeza clava Chavín se añade una guía de interpretación estilizada con rasgos humanos/felínicos y espiga posterior, basada en [Ministerio de Cultura](https://museos.cultura.pe/sites/default/files/publicaciones/pdf/expoicpp.pdf) y [Museo Larco](https://www.museolarco.org/exposicion/exposicion-permanente/exposicion-en-linea/introduccion/cabezas-clavas-2/). La descripción explícita del usuario tiene prioridad sobre esa guía. Las referencias STEP independientes de evaluación nunca se envían a la IA.

Los tres runtimes exportan un STL nativo con desviación lineal **absoluta de 0,02 mm** y angular **0,05 rad**. El STEP conserva la geometría B-Rep; el STL común del evaluador mantiene su perfil de comparación previamente definido. El visor suaviza normales de curvas y preserva discontinuidades angulares de 30° o más; esto afecta únicamente la iluminación, no las coordenadas ni los archivos. El encuadre inicial adapta la cámara al volumen y al tamaño del visor para mostrar la pieza con mayor claridad.

**La validez CAD y la resolución STL no certifican parecido visual o fidelidad arqueológica.** La parada sigue ocurriendo al obtener el primer CAD válido y exportable en open-loop/closed-loop. Una réplica exacta necesita una referencia y una evaluación de semejanza apropiada; los rasgos ausentes no se recuperan solo aumentando la cantidad de triángulos. Quality Loop tiene su propio protocolo versionado (`ciel-quality-loop-v2`); la revisión v2 corrige la detección de agujeros, alinea las vistas con el frente del plan y clasifica los errores de proveedor. Los informes v1 conservan su versión y no deben combinarse con v2. Las campañas nuevas usan `v6-quality-loop-geometric-plan`. Las campañas de plantilla v5 o anterior conservan sus resultados históricos, pero deben recrearse para ejecutar nuevas condiciones con la versión actual.

## Suscripciones de Codex y Antigravity en segundo plano

Los proveedores `codex-cli` y `antigravity-cli` ejecutan los CLI oficiales con la sesión
de la cuenta del usuario: una llamada independiente por generación, corrección o
candidato. Funcionan con open-loop, closed-loop (hasta cinco generaciones) y Quality
Loop/Best-of-N (hasta tres candidatos por ciclo). No requieren una ventana de terminal
visible. Los resultados pasan por la misma política AST, supervisor CAD y evaluación.

La ejecución no interactiva está documentada por
[OpenAI](https://learn.chatgpt.com/docs/non-interactive-mode) y
[Google](https://www.antigravity.google/docs/cli/headless/).
Instala `codex` y el **CLI `agy`**, que es distinto del lanzador del IDE Antigravity.
Inicia sesión una vez con `codex login` y una sesión interactiva `agy` usando tus cuentas.
Codex debe mostrar `Logged in using ChatGPT` en `codex login status`. El adaptador
rechaza una sesión Codex autenticada por API y una configuración `modelProvider=gemini`
de Antigravity; elimina las claves de API heredadas del entorno del proceso hijo.
Las sesiones las administran los CLI oficiales y nunca se copian a la base de datos,
imágenes Docker o interfaz.

Para Linux/macOS con Docker, el puente corre como el usuario de escritorio, conservando
acceso a su keyring. Usa un directorio externo privado (modo `700`) y un socket Unix
(modo `600`); no abre ningún puerto. El puente requiere solo Python estándar.

```bash
mkdir -p "$HOME/.local/state/agente-ciel/puente"
chmod 700 "$HOME/.local/state/agente-ciel/puente"
python -m aplicacion.puente_cli --socket "$HOME/.local/state/agente-ciel/puente/suscripciones.sock"
```

Para mantenerlo en background en Linux, un servicio de usuario de systemd puede ejecutar
ese comando con `WorkingDirectory` apuntando al repositorio y un `PATH` que incluya ambos
CLI. Debe ejecutarse en la sesión del mismo usuario autenticado. En este equipo está
instalado como `agente-ciel-suscripciones.service`; puedes consultar su estado con
`systemctl --user status agente-ciel-suscripciones`.
El puente detecta y retira sockets abandonados tras un apagado para poder reiniciarse;
si otro puente sigue escuchando, conserva su socket y rechaza el segundo arranque.

Añade `CLI_PUENTE_DIRECTORIO=/ruta/absoluta/al/directorio/puente` al archivo externo de
entorno, conserva su modo `600` y habilita el archivo Compose adicional:

```bash
docker compose --env-file /ruta/al/entorno.env -f compose.yaml -f compose.suscripciones.yaml build api trabajador
docker compose --env-file /ruta/al/entorno.env -f compose.yaml -f compose.suscripciones.yaml up -d api trabajador
```

Opciones del puente: `CODEX_CLI_BIN` y `ANTIGRAVITY_CLI_BIN` cambian la ruta del ejecutable;
`CODEX_CLI_MODELO` y `ANTIGRAVITY_CLI_MODELO` fijan un modelo compatible con la cuenta.
Si se omiten, se usa la selección predeterminada del CLI. `CLI_TIMEOUT_SEGUNDOS` vale
900 por defecto (rango 30–10800); configura el mismo valor en el puente y en Docker.
`CLI_PROVEEDORES=codex-cli,antigravity-cli` controla los proveedores que anuncia Docker.
En un backend nativo, incluido Windows, usa `CLI_LOCAL_HABILITADO=1` para ejecutar los
CLI directamente y omite `CLI_PUENTE_SOCKET`. El puente Unix corresponde a Linux/macOS;
no convierte todavía el proyecto en un instalador de escritorio.

La interfaz también muestra los **modelos concretos** anunciados por cada CLI, agrupados
por proveedor. El catálogo Codex procede de `codex app-server` mediante `model/list`;
Antigravity usa `agy models`. Son consultas de metadatos sin turnos de inferencia, con
caché de cinco minutos. El último catálogo correcto se guarda de forma atómica en
`$XDG_STATE_HOME/agente-ciel/catalogos` (por defecto `~/.local/state/agente-ciel/catalogos`;
en Windows, `%LOCALAPPDATA%/agente-ciel/catalogos`). `CLI_CATALOGO_DIRECTORIO` permite
cambiar esta ruta. Solo se guardan metadatos de modelos, sin sesiones ni credenciales.
Si una consulta falla después de reiniciar, se conserva ese catálogo con estado
`guardado` y se vuelve a consultar después de diez segundos en la siguiente petición.
Una consulta correcta reemplaza el catálogo anterior, incluidos los modelos retirados.
Sin catálogo previo, permanece la opción predeterminada del CLI. El error se expone
en `suscripciones.catalogos` de `/api/opciones`. La interfaz muestra el identificador
exacto de cada modelo y refresca las opciones cada treinta segundos y al recuperar
el foco, por lo que también recoge la recuperación del puente después del arranque.
El catálogo anunciado no certifica acceso ni cuota de la cuenta.

El campo **Nivel de esfuerzo** usa los niveles y el predeterminado anunciados por cada
modelo concreto. Codex aporta `supportedReasoningEfforts` y `defaultReasoningEffort`;
se envía la elección con `model_reasoning_effort`. El adaptador ofrece `low`, `medium`,
`high`, `xhigh` y `max` cuando aparecen en ese catálogo. `ultra` requiere delegación
automática y se excluye del transporte CAD de un turno sin subagentes.
Antigravity se consulta mediante `agy --print /effort --model ID --output-format json`,
aceptando únicamente metadatos de cero turnos. Si el esfuerzo define una variante de
Gemini, cambiarlo también cambia el identificador exacto seleccionado y se envía
`--effort` con ese mismo nivel. Los modelos que el CLI anuncia como no ajustables
mantienen el campo deshabilitado; GPT-OSS muestra el `medium` de su identificador,
y para Claude no se inventa un presupuesto numérico de pensamiento.

En campañas se elige el esfuerzo de cada modelo por separado. La API acepta
`esfuerzos_por_modelo` en creación y previsualización; el campo global anterior sigue
aplicándose solo a DeepSeek. Los valores se congelan en perfiles, condiciones,
ejecuciones y trazas de cada intento, usando `ciel-esfuerzo-por-modelo-v1` y el transporte
`ciel-cli-subscription-v3`. Las ejecuciones históricas sin selección explícita siguen
sin enviar una elección de esfuerzo. Las consultas de metadatos no generan CAD ni
consumen turnos de inferencia.

Una selección como `codex-cli::gpt-6.1-sol` o
`antigravity-cli::gemini-3.1-pro-high` se guarda como identidad de la ejecución y se envía
al CLI mediante `--model` en cada generación, reparación y candidato. Esta selección
explícita tiene prioridad sobre `CODEX_CLI_MODELO`/`ANTIGRAVITY_CLI_MODELO` del puente.
Los nombres del ejemplo solo estarán disponibles si aparecen en el catálogo local.
Para los revisores se elige independientemente un modelo concreto del mismo catálogo;
solo se ofrecen revisores Codex que anuncien entrada de imágenes. Antigravity conserva
NVIDIA para la revisión visual. La API acepta estas mismas identidades en `modelo` y
`proveedor_revisores`. Las ejecuciones anteriores conservan su elección y trazas.

En la interfaz selecciona el generador y, para Quality Loop, **Planificador y revisores**:

| Selección de revisores | Planificación, código y crítica textual | Revisión visual |
|---|---|---|
| NVIDIA (predeterminado) | API NVIDIA | API NVIDIA |
| Codex | Suscripción Codex | Suscripción Codex, con PNG adjunto |
| Antigravity | Suscripción Antigravity | API NVIDIA |

La API acepta `proveedor_revisores` con `nvidia`, `codex-cli`, `antigravity-cli` o una
identidad concreta del catálogo en
`POST /api/ejecuciones`. Se guarda con la ejecución. Antigravity mantiene NVIDIA para
las imágenes porque este adaptador usa la entrada headless documentada de texto, que
no admite bloques multimedia. Codex permite todos los roles sin NVIDIA. Los roles son
llamadas orquestadas por el backend; no dependen de un mecanismo interno de subagentes.
Las ejecuciones Quality Loop con suscripción se identifican como
`ciel-quality-loop-cli-v2` y `ciel-cli-routing-v2`; el perfil CLI usa
`ciel-cli-subscription-v2`. Las versiones v1 conservan las selecciones predeterminadas
del CLI usadas antes de añadir el catálogo. Los experimentos históricos mantienen
su protocolo y sus resultados. La clave DeepSeek es opcional al levantar Docker y solo
se necesita cuando se elige ese proveedor.

Las cuotas, permisos del plan, caducidad de sesión y disponibilidad de modelos siguen
aplicándose. El primer inicio de sesión y cualquier reautenticación requieren intervención
del usuario; no es posible garantizar automatización ilimitada. Antigravity necesita un
keyring accesible y desbloqueado. No se activan compras de créditos ni respaldos de API
para fallos de generación CLI. Ante timeout no se repite la solicitud: un fallo de generación
bloquea la ejecución; los errores de planificación/revisión se registran siguiendo el
protocolo Quality Loop existente y nunca se convierten en aprobación del revisor.
El puente procesa una sola inferencia a la vez y rechaza
solicitudes concurrentes sin consumir cuota. Los límites de tokens de los proveedores API
no pueden imponerse al CLI; Quality Loop conserva reservas estimadas y consumo observado,
sin presentarlos como un límite duro de suscripción. El coste de suscripción no se convierte
en una tarifa API ni se certifica como cero. Si el CLI no informa tokens o modelo efectivo,
se registra esa incertidumbre en el perfil de la llamada.

`GET /api/opciones` informa los proveedores configurados y la salud del puente. La salud
comprueba disponibilidad del transporte y los ejecutables, sin consumir inferencias ni
certificar que la cuenta tiene cuota. Las pruebas `test_suscripciones.py` simulan todas
las respuestas CLI; la validación de instalación no debe consumir cuotas reales.

## Quality Loop experimental

Quality Loop es un modo individual, separado de las campañas históricas. Usa Nemotron Super como planificador y Kimi K3 como respaldo tras respuestas explícitamente inválidas; no duplica llamadas ante un timeout incierto. Si el plan NVIDIA falla o no conserva las cotas literales, intenta crear un plan determinista desde la descripción y registra el error y el origen local. El plan Pydantic versionado se guarda antes de modelar. La generación se puede elegir entre DeepSeek directo, Ollama y cuatro modelos NVIDIA disponibles en el selector: Nemotron Super, Kimi K3, Gemma 4 31B y GLM 5.3. Gemma y GLM están habilitados tras pasar una muestra CadQuery por la política AST, el supervisor y la exportación. Nemotron Super es el revisor de código predeterminado y GLM 5.3 funciona como alternativa cuando una respuesta estructurada está malformada. CadQuery, build123d y FreeCAD mantienen sus propios contratos de exportación.

`GeometricPlan` (`ciel-geometric-plan-v1`) especifica unidades mm, clase `MECHANICAL_PRECISE`/`ORGANIC_FREEFORM`/`HYBRID`, coordenadas y orientación, cotas globales, caja/centroide/volumen cuando se declaran, features con `feature_id`, dependencias y regiones, simetrías, restricciones, operaciones, perfiles, trayectorias, espesores, agujeros, cavidades, relieves, cortes, tolerancias, procedencia `specified`/`inferred` y criterios verificables. Planner interpreta; Modeler genera Python para el motor seleccionado; Repairer recibe el plan, código completo anterior, revisiones, métricas y features a preservar. La biblioteca `recipes.py` entrega determinísticamente solo las orientaciones pertinentes al plan; no contiene piezas de respaldo.

Cada candidato pasa por política AST, revisor de código, runtime CAD aislado y evaluador determinista. Si Nemotron devuelve JSON malformado, el revisor prueba una vez GLM 5.3; no repite ante timeout o transporte incierto. Un error o rechazo del revisor de código queda registrado como rechazo y aun así permite comprobar el código con la política estática y el supervisor; el Quality Gate se mantiene cerrado. Solo un candidato con éxito técnico recibe la lámina ortográfica reproducible de ocho vistas, Kimi K3 como revisor visual y Nemotron Super como crítico geométrico predeterminado. El crítico propone prioridades y rasgos que se deben preservar; no modifica código. El Repairer recibe el código completo del candidato ganador anterior, diagnósticos, plan, métricas y lista `preservar`. El modo termina al aceptar Quality Gate o tras tres ciclos. **Best-of-N** es opcional y genera hasta tres candidatos con el mismo plan, descripción, modelo y motor por ciclo; registra y clasifica cada candidato por separado.

Los errores de revisores se registran con rol, modelo, clase de error y latencia, sin repetir automáticamente una llamada cuyo resultado pueda haberse facturado. Los errores de revisión visual o crítica consumen ese candidato y dejan guardados su STEP/STL, lámina y resultado técnico; `technical_success` puede ser verdadero mientras `quality_success` es falso. Si falla la generación IA, CadQuery puede usar un respaldo paramétrico local limitado a planes clasificados como casa; cualquier otro tipo de pieza no recibe una geometría genérica presentada como resultado. La interfaz muestra los informes y fallos para auditoría. El estado terminal puede indicar calidad rechazada aunque haya un archivo CAD técnicamente válido.

El límite predeterminado es 40 llamadas de modelo y 800.000 tokens presupuestados por ejecución; DeepSeek directo usa hasta 32.768 tokens de salida por generación en este modo. Se puede ajustar con `MAXIMO_LLAMADAS_QUALITY_LOOP`, `MAXIMO_TOKENS_QUALITY_LOOP` y `MAXIMO_TOKENS_SALIDA_QUALITY_GENERADOR`. Los tokens de NIM que la API no informe se presupuestan con una estimación conservadora basada en tamaño del prompt, límite de salida e imágenes. Los costos NVIDIA sin tarifa verificable se muestran como desconocidos; la aplicación no los presenta como facturas ni afirma que el presupuesto estimado sea un límite monetario.

Quality Loop conserva separados `technical_success` (CAD válido, sólido y exportable) y `quality_success` (aceptación de Quality Gate). El puntaje versionado (`ciel-quality-metrics-v2`) promedia las métricas disponibles ponderadas y renormaliza por la suma de sus pesos; las métricas esenciales deben estar disponibles. La aceptación requiere éxito técnico, topología 1.0, revisiones de código, visual y crítica aceptadas, ningún error crítico, cotas explícitas dentro de tolerancia, features esenciales medibles correctas y puntuación mínima de **0,85**. Estos pesos son una regla del protocolo reproducible, no una certificación física ni una garantía de fidelidad.

| Métrica | Mecánica precisa | Orgánica libre | Híbrida |
|---|---:|---:|---:|
| Cotas | 0,32 | 0,08 | 0,20 |
| Topología | 0,12 | 0,08 | 0,11 |
| Features | 0,24 | 0,19 | 0,22 |
| Silueta semántica | 0,04 | 0,23 | 0,13 |
| Proporciones | 0,04 | 0,14 | 0,08 |
| Simetría declarada | 0,04 | 0,06 | 0,05 |
| Centroide | 0,04 | 0,02 | 0,04 |
| Área superficial | 0,04 | 0,03 | 0,04 |
| Hausdorff P95 | 0,04 | 0,04 | 0,04 |
| Volumen | 0,05 | 0,02 | 0,04 |
| Silhouette IoU | 0,03 | 0,03 | 0,03 |
| Consistencia de normales | 0,02 | 0,03 | 0,03 |
| Semejanza con referencia | 0,06 | 0,10 | 0,06 |

El informe conserva puntuaciones parciales, pesos, estado (`calculated`, `not_available`, `not_applicable` o `unsupported`), unidad, algoritmo, muestras, semilla, tolerancia, perfil y versión. La validez técnica no sustituye la semejanza geométrica: un CAD puede ser exportable y aun así fallar features, silueta o el Gate.

Por defecto ningún rol de IA recibe la referencia STEP independiente. El evaluador solo mide contra ella si `QUALITY_ALLOW_REFERENCE_METRICS=1` y la ejecución está asociada a un caso; el informe identifica entonces el protocolo `quality-v2-reference-authorized`. Esa opción cambia el protocolo de evaluación y debe separarse de los resultados sin referencia. El endpoint `GET /api/proveedores/nvidia/catalogo` consulta el catálogo bajo demanda. Los IDs permitidos incluyen Nemotron 3 Ultra/Super, Laguna XS 2.1, Kimi K3, DeepSeek V4.1 Flash, GLM 5.3 y Gemma 4 31B. Los modelos admitidos internamente para roles no aparecen todos como generadores en la interfaz. `nvidia/cosmos3-nano-reasoner` no estaba en el catálogo comprobado para la clave actual y queda desactivado.

### Disponibilidad de modelos NVIDIA para generar código

El 2026-10-07 se consultó `/v1/models` desde el servicio API con la credencial NVIDIA externa: autenticación HTTP 200 y 80 IDs disponibles. La página pública [NVIDIA Build](https://build.nvidia.com/models?pageSize=96) mostraba 97 modelos; esa lista de tarjetas no significa que todos tengan un endpoint de chat habilitado para esta cuenta. Se cribaron nueve modelos con el mismo prompt pequeño de CadQuery, límite de 90 s, control de sintaxis/contrato y, para las mejores muestras, política AST y supervisor aislado que valida sólido y exportación. Estas pruebas son una selección inicial, no un benchmark ni evidencia de estabilidad para los 60 casos.

| Modelo | Resultado del cribado actual | Decisión |
| --- | --- | --- |
| [Gemma 4 31B](https://build.nvidia.com/google/gemma-4-31b-it) | Dos respuestas HTTP 200 (21,6 y 32,8 s); ambas asignaron `resultado`; la segunda pasó política, ejecución CadQuery y exportación STEP/STL | Opción recomendada para iniciar pruebas de generación; mantener el default de la aplicación sin cambios hasta medir más casos |
| [GLM 5.3](https://build.nvidia.com/z-ai/glm-5.3) | Dos respuestas HTTP 200 (60,5 y 26,7 s); la segunda pasó política, ejecución CadQuery y exportación STEP/STL | Segunda opción recomendada; latencia variable |
| [Nemotron 3 Super](https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b) | Dos respuestas HTTP 200 (10,6 y 7,4 s); una muestra cumplió el contrato, la otra omitió `resultado` y falló en CAD | Mantener como opción existente y alternativa de baja latencia; no depender de él sin el loop de validación |
| [Kimi K3](https://build.nvidia.com/moonshotai/kimi-k3) | Una respuesta válida en 49,8 s; la segunda llamada agotó 90 s | Mantener como alternativa experimental |
| [Nemotron 3 Ultra](https://build.nvidia.com/nvidia/nemotron-3-ultra-550b-a55b) | HTTP 200 en 12,3 s y sintaxis válida, pero no asignó `resultado` | No exponer como generador todavía |
| [Kimi K2.6](https://build.nvidia.com/models?pageSize=96) | Aunque aparece en `/v1/models`, su endpoint respondió HTTP 404 | No usar hasta que NVIDIA habilite el endpoint |
| [DeepSeek V4.1 Flash en NVIDIA](https://build.nvidia.com/deepseek-ai/deepseek-v4.1-flash) | Timeout a los 90 s | No usar como generador por ahora |
| [GLM 5.3 Flash](https://build.nvidia.com/z-ai/glm-5.3-flash) | Timeout a los 90 s | No usar como generador por ahora |
| [Laguna XS 2.1](https://build.nvidia.com/poolside/laguna-xs-2.1) | HTTP 503 en 0,4 s | Endpoint no disponible en esta prueba |

Gemma 4 31B y GLM 5.3 ya están habilitados en el selector NVIDIA de generación, junto con Super y Kimi K3. Para errores recuperables, Gemma y GLM prueban una sola vez el uno al otro como respaldo; cada intento conserva ambos modelos y la causa en su perfil. No se reenvía la misma solicitud al mismo endpoint; un timeout puede implicar que el proveedor ya procesó la llamada. El default de Quality Loop sigue siendo Nemotron Super hasta validar un conjunto más amplio. Super usa `reasoning_effort=low`; los demás candidatos probados no recibieron un parámetro de esfuerzo. En una muestra breve, Gemma y GLM produjeron sólidos válidos y exportables, pero eso no acredita la geometría semántica ni predice resultados para los tres motores o las distintas clases de dificultad.

Tras desplegar el cambio, una ejecución real `open-loop` con Nemotron Super y CadQuery generó al primer intento una placa de 20 × 10 × 2 mm con dos agujeros pasantes de Ø2 mm. El supervisor informó sintaxis, ejecución, CAD y exportación válidos, produjo STEP y STL, y el evaluador midió **387,43 mm³**, coincidente con `400 − 2·π·1²·2 ≈ 387,43 mm³`. La inferencia tardó 12,6 s y la etapa CAD 3,8 s en esa ejecución. Esta comprobación valida el recorrido de generación y exportación para un caso sencillo; no valida por sí sola los modelos alternativos, los otros motores ni la fidelidad de las piezas complejas.

El 2026-10-07 se recorrió además Quality Loop con el mismo caso mecánico y NVIDIA real: planner, generador, code reviewer, Kimi K3 visual, crítico, runtime CAD y evaluador. Kimi visual devolvió las puntuaciones con el esquema formal; dos respuestas del crítico usaron `errors` en lugar de `errores` y se registraron como intentos perdidos. El tercer candidato falló en CAD. La ejecución terminó con `technical_success=true`, `quality_success=false`, archivos CAD conservados y `estado_protocolo=reviewer_attempts_exhausted`. Después se repitió directamente la revisión visual contra una lámina real (11,5 s, esquema válido) y la crítica sobre sus métricas (9,5 s, esquema válido con alias normalizado). Es una verificación funcional de un caso mecánico; no demuestra aceptación del Quality Gate, rendimiento estadístico ni fidelidad para las clases orgánica e híbrida.

### Comprobación adicional con la casa de 40 × 25 × 12 mm

En una prueba histórica de la casa, el catálogo NVIDIA autenticado respondió HTTP 200 y Nemotron Super completó `closed-loop` con STEP/STL válidos, pero sin demostrar que todas las features semánticas estuvieran presentes. Kimi K3 tuvo una llamada que agotó el timeout. Nueve candidatos de un `quality-loop` anterior se perdieron por respuestas estructuradas inválidas de Nemotron; eso motivó el fallback de revisión a GLM 5.3 para `malformed_response`. El cribado posterior resumido arriba habilitó Gemma 4 31B y GLM 5.3 también como generadores, con resultados de pruebas separados.

El registro previo de GLM 5.3 como generador correspondía a una sola llamada larga que agotó el timeout. Las pruebas posteriores con el mismo prompt corto encontraron una respuesta que pasó política, CadQuery y exportación, por lo que ahora aparece como alternativa experimental en el selector. Los fallos de cada llamada y las alternativas usadas se mantienen en la auditoría.

En otra repetición histórica de `open-loop`, Kimi K3 produjo cortadores que no modificaron el volumen y Nemotron Super usó una operación inexistente; ambos trabajos terminaron con diagnósticos, sin procesos bloqueados. Un `quality-loop` anterior probó nueve candidatos y no generó CAD válido. Esas ejecuciones precedieron al cribado resumido en la tabla actual: la elección recomendada para empezar a probar generación es Gemma 4 31B, seguida de GLM 5.3, con Nemotron Super y Kimi K3 como alternativas experimentales. La validez geométrica completa requiere evaluación por prompt, motor y ciclo; una muestra exportable no garantiza que la pieza represente la descripción.

## Conjunto, referencias y campañas

`datos/prompts_60_v1.json` es el conjunto principal; `datos/construir_conjunto.py` documenta sus 60 descripciones, familias y fundamentos de dificultad. Al arrancar, la API lo importa de modo idempotente y rechaza una nueva carga que use su nombre y versión con contenido diferente. Se pueden importar otros conjuntos JSON/CSV, con 50–100 casos para evaluación o menos en desarrollo. El conjunto principal está congelado: el texto y la clasificación no cambian dentro de una campaña.

La interfaz muestra los 60 casos y permite adjuntar a cada uno una **referencia STEP diseñada independientemente**, con procedencia y hash. No se envía al proveedor de IA. Una referencia de un caso ya ensayado no se modifica; para cambiarla se crea otro conjunto/versionado. Una campaña al iniciarse congela los hashes de referencias y de las imágenes CAD, además del conjunto, parámetros y orden aleatorio por bloques. Si cambia una imagen antes de reanudar, debe crearse una campaña nueva.

Para preparar una campaña, seleccionar casos, modelos, motores, modos, repeticiones y semilla; consultar primero la vista previa y luego guardar el borrador. **Guardar el borrador no llama a ninguna IA.** El botón «Iniciar campaña» sí activa la cola. Hay controles de pausa, reanudación, cancelación de pendientes y actualización del tope. Una repetición de 60 casos para Flash y Pro con los tres motores y dos modos programa **720 ejecuciones** y un máximo de **2.160 generaciones**. La vista muestra estados separados para desenlaces científicos, bloqueos, cancelaciones y pendientes.

En open-loop y closed-loop, la parada se produce en el primer CAD válido y exportable. En Quality Loop, cada candidato técnicamente correcto se mide y el programa termina únicamente cuando Quality Gate lo acepta o el presupuesto/ciclos se agotan. Cada motor produce STEP y STL; FreeCAD entrega además FCStd. Un verificador independiente vuelve a abrir STEP/STL antes de declarar éxito de exportación. Después se genera un STL común desde STEP y se estudian tanto la malla nativa como la común. Un fallo posterior del análisis no consume otro intento de IA ni convierte en fallo un CAD previamente exportado.

## Métricas

- **Compile Rate acumulado hasta el intento k:** ejecuciones evaluables cuyo script terminó sin excepción por primera vez hasta k, dividido entre N evaluable. Un script que corre pero no devuelve un sólido válido sí cuenta como éxito de ejecución.
- **IR-CAD:** ejecuciones evaluables sin CAD válido y exportable, dividido entre N evaluable. No es necesariamente el complemento del Compile Rate.
- **Watertight y DangEL:** se calculan sobre un STL final por ruta. Las tasas de malla informan el número de STL realmente analizados y su cobertura frente a la campaña.
- **IoU B-Rep y Chamfer digital cuadrático bidireccional [mm²]:** solo se calculan con un STEP de referencia independiente. Chamfer usa 8.192 puntos por superficie y una semilla fija. Sin referencia aparece «sin referencia», no cero.
- **Quality Loop:** el éxito técnico y el de calidad se publican en columnas separadas. El Quality Gate conserva la fórmula, pesos, versión, puntuaciones parciales, informes de revisores, artefactos multivista, candidatos y retroalimentación de reparación.
- Los gráficos por iteración usan la propia cohorte closed-loop. El open-loop aparece como condición independiente; las comparaciones con CadQuery se calculan sobre pares de casos evaluables comunes.

Los informes incompletos se rotulan provisionales. Las tasas con denominador cero se representan como no calculables. La interfaz ofrece CSV de métricas y JSON con el manifiesto, las respuestas, scripts, diagnósticos, archivos, topología y comparaciones. El JSON puede incluir respuestas y scripts extensos; se debe custodiar como evidencia de investigación.

## API y pruebas

La interfaz se divide en cinco páginas: **Generar pieza**, **Resultado 3D**, **60 casos**, **Campañas** y **Métricas**. La navegación conserva los campos de generación y de campaña mientras la sesión permanece abierta. El resultado admite un enlace directo `/#/resultado/{id}`; recargarlo recupera la ejecución desde la API. Los botones Atrás y Adelante funcionan con estas rutas. Los temas claro y oscuro siguen disponibles en todas las páginas.

El campo **Nivel de esfuerzo** está separado del modelo y permanece bloqueado mientras no se seleccione uno. Flash y Pro permiten **Bajo (`low`), Alto (`high`) y Máximo (`max`)**, según la [documentación oficial de DeepSeek](https://api-docs.deepseek.com/guides/thinking_mode/). Se propone Máximo para mantener el comportamiento anterior, pero la elección se guarda y se envía como `reasoning_effort` a DeepSeek en todos los intentos y correcciones. La API acepta `esfuerzo_razonamiento` en generaciones y campañas; si un cliente anterior lo omite, usa `max` para DeepSeek. Para Ollama no se aplica este control y la API rechaza un esfuerzo explícito.

Una campaña congela un mismo nivel de esfuerzo para sus modelos DeepSeek, sus condiciones y ejecuciones; los perfiles locales mantienen su configuración propia. El manifiesto JSON exportado conserva esos perfiles. Para comparar niveles distintos se preparan campañas distintas. Las ejecuciones antiguas muestran el esfuerzo de sus trazas si existe; no se atribuye un nivel inventado a resultados sin registro.

Endpoints principales:

| Ruta | Uso |
|---|---|
| `GET /api/opciones` | Motores, modos, modelos y presupuestos disponibles |
| `GET /api/proveedores/nvidia/catalogo` | Consulta explícita del catálogo NVIDIA y roles configurados |
| `GET /api/conjuntos` y `GET /api/conjuntos/{id}` | Conjuntos y 60 casos |
| `PUT /api/casos/{id}/referencia` | STEP independiente y procedencia |
| `POST /api/ejecuciones` | Generación individual; `modo=quality-loop` habilita el protocolo avanzado y `best_of_n` es opcional |
| `GET /api/ejecuciones/{id}` | Intentos, archivos, plan y evidencia Quality Loop |
| `POST /api/campanas/previsualizar` | Tamaño y costo estimado de la matriz |
| `POST /api/campanas` | Borrador de campaña |
| `POST /api/campanas/{id}/iniciar`, `/pausar`, `/cancelar` | Control de cola |
| `PATCH /api/campanas/{id}/presupuesto` | Ajustar el tope estimado |
| `GET /api/campanas/{id}/metricas` | Tasas con denominadores y comparaciones |
| `GET /api/campanas/{id}/metricas.csv` y `/datos.json` | Exportaciones |

Pruebas del protocolo, bucles y Quality Loop (todos los proveedores se simulan):

```text
  docker run --rm --network agente-ciel_default -v "$PWD:/servicio:ro" ciel-aplicacion:piloto python -m unittest discover -s pruebas -v
```

Pruebas geométricas del evaluador:

```text
  docker run --rm -v "$PWD:/servicio:ro" ciel-evaluador:piloto python -m unittest discover -s pruebas -p test_evaluador.py -v
```

El piloto real B01 ejecutó 12 condiciones (Flash/Pro × tres motores × dos modos); las 12 generaron STEP/STL/FCStd cuando correspondía, se analizaron ambas rutas STL y se compararon con una referencia manual independiente. Es una prueba de integración de un caso básico, **no** un resultado estadístico de la matriz de 60 casos. La campaña principal de 720 ejecuciones permanece como borrador hasta que se inicie expresamente desde la interfaz o API.


## Límites de modelos y texto (protocolo v7)

Desde `v7-limites-oficiales-sin-recorte`, las nuevas ejecuciones open-loop y closed-loop
no tienen el antiguo tope de 4.000 caracteres de entrada ni de 90.000 bytes de código.
Los mensajes, el programa y el historial se envían completos. El proveedor puede rechazar
una solicitud que exceda su contexto; la aplicación no elimina contenido para hacerla caber.
El límite de entrada incluye instrucciones e historial, no solo la descripción del usuario.
Una ventana compartida tampoco permite sumar simultáneamente el máximo contexto y la máxima salida.

Valores consultados el **2026-10-20**, versionados en `aplicacion/limites_modelos.py` y
expuestos en `/api/opciones` con enlaces oficiales. Las campañas nuevas y cada intento
registran estas referencias y el perfil efectivo enviado al proveedor:

| Modelo exacto | Entrada o contexto publicado | Salida publicada para esta ruta |
| --- | --- | --- |
| `deepseek-flash`, `deepseek-v4-pro` | 1.048.576 de contexto compartido | 393.216 |
| `gpt-6.1-sol`, `gpt-6-astra`, `gpt-6-sol`, `gpt-6-luna`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna` | 922.000 entrada; 1.050.000 contexto | 128.000 (referencia API) |
| `gemini-3.8-flash-low`, `gemini-3.8-flash-medium`, `gemini-3.8-flash-high` | 1.048.576 entrada; presupuesto separado | 65.536 (referencia API) |
| `claude-sonnet-4-6`, `claude-opus-4-6-thinking` | 1M de contexto compartido | 128K (referencia API síncrona) |
| `gpt-oss-120b-medium` | 131.072 contexto compartido | 131.072 menos el espacio consumido por la entrada (referencia del modelo) |
| `nvidia/nemotron-3-super-120b-a12b` | 1.048.576 contexto compartido | 32.768 en NVIDIA NIM |
| `moonshotai/kimi-k3` | 1.048.576 contexto compartido | 65.536 en NVIDIA NIM |
| `google/gemma-4-31b-it` | 262.144 contexto compartido | 32.768 en NVIDIA NIM |
| `z-ai/glm-5.3` | 1.048.576 contexto compartido | 131.072 |

Fuentes: [DeepSeek API](https://api-docs.deepseek.com/api/create-chat-completion/),
[contexto DeepSeek](https://api-docs.deepseek.com/quick_start/agent_integrations/codex/),
[OpenAI GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol)
(cada GPT tiene también su página exacta enlazada en el catálogo),
[Gemini](https://ai.google.dev/gemini-api/docs/tokens),
[Claude Sonnet](https://platform.claude.com/docs/en/models/sonnet-4-6/overview),
[Claude Opus](https://platform.claude.com/docs/en/models/opus-4-6/overview),
[GPT-OSS](https://developers.openai.com/api/docs/models/gpt-oss-120b),
[Nemotron NIM](https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3-super-120b-a12b-infer),
[Kimi NIM](https://docs.api.nvidia.com/nim/reference/moonshotai-kimi-k3-infer),
[Gemma NIM](https://docs.api.nvidia.com/nim/reference/google-gemma-4-31b-it-infer) y
[GLM API](https://docs.z.ai/api-reference/llm/chat-completion).

Las solicitudes API de los modelos listados fijan `max_tokens` en su máximo documentado.
El respaldo DeepSeek del protocolo histórico de generación NVIDIA usa también el máximo de DeepSeek. El protocolo de recuperación NVIDIA descrito abajo conserva el modelo solicitado y no activa ese respaldo.
GPT y Antigravity se usan mediante sus CLI de suscripción: estos adaptadores no exponen
un parámetro de tokens de salida. No se inventan flags ni se cambia a una API facturada;
los valores de sus creadores son referencias, **no una garantía de que la suscripción
exponga la misma capacidad**. La aplicación no añade límites de tokens a estas rutas.
Para un modelo nuevo sin documentación verificada el catálogo informa la incertidumbre,
sin asignarle el máximo de otro modelo.

El cambio de plantilla y de imágenes CAD exige crear campañas nuevas; las campañas históricas
conservan sus perfiles y resultados y se bloquean si se intenta ejecutarlas bajo otro protocolo.
El Quality Loop oculto conserva sus presupuestos históricos. Los límites de aislamiento CAD
(memoria, tiempo, archivos geométricos y procesos) son independientes de los tokens y se conservan.

## Exportaciones durante la generación

El seguimiento de campañas muestra **Ver ejecución** y **Exportar ejecución ZIP** para
la generación activa; si aún está en cola muestra la próxima ejecución pendiente.
Las descargas están disponibles desde que existe el trabajo, aunque todavía no haya CAD.
Se identifican como provisionales hasta que termina la cohorte evaluable. Una descarga
contiene lo disponible en ese momento: para obtener resultados posteriores hay que descargarla de nuevo.

En Campañas y Métricas se pueden descargar:

- Figuras de Compile Rate o éxito CAD exportable en **PNG, SVG y PDF**, para todos los
  prompts o una dificultad. Conservan los denominadores y la separación entre ejecución
  de código, CAD válido y aceptación de calidad; la ausencia de evaluables no se convierte en cero.
- Métricas CSV, tabla Digital Metrics CSV, datos y trazas JSON, y registros separados
  de ejecuciones, intentos y geometría CSV.
- Un ZIP con prompts, CSV, figuras de ambos criterios y de las dificultades presentes,
  código y respuesta de cada intento, solicitudes y archivos CAD registrados.

La tabla Digital Metrics y el ZIP incluyen las referencias versionadas de literatura del
desktop (`literatura_digital_v1.json`). Se conservan sus fuentes y advertencias: son contexto,
con otros datasets y criterios, y no se usan para construir rankings ni alterar las tasas de la campaña.

Cada resultado individual ofrece también su ZIP, JSON completo y CSV de intentos,
antes y después de finalizar. El ZIP conserva STL, STEP, Python, FCStd y cualquier otra
salida ya registrada, sin fabricar archivos CAD para trabajos aún pendientes.
Incluye un manifiesto SHA-256 y una lista de archivos ausentes o alterados. Se construye
como archivo temporal en el servidor y se elimina después de la descarga. No incluye
credenciales ni una copia completa de PostgreSQL. El formato se versiona como
`ciel-exportaciones-v1`; no modifica campañas, prompts ni protocolos de generación históricos.

Rutas principales:

```text
/api/campanas/{id}/figura.png?tipo=codigo&nivel=todos
/api/campanas/{id}/figura.svg?tipo=cad&nivel=basico
/api/campanas/{id}/figura.pdf?tipo=codigo&nivel=complejo
/api/campanas/{id}/tabla-digital.csv
/api/campanas/{id}/registros/ejecuciones.csv
/api/campanas/{id}/registros/intentos.csv
/api/campanas/{id}/registros/geometria.csv
/api/campanas/{id}/entregables.zip
/api/ejecuciones/{id}/datos.json
/api/ejecuciones/{id}/intentos.csv
/api/ejecuciones/{id}/entregables.zip
```

## Campañas simultáneas

El trabajador usa `CIEL_CONCURRENCIA=2` por defecto. Se pueden ejecutar dos campañas a la vez; dentro de cada campaña se conserva el orden de su matriz y los máximos de uno/cinco intentos. Puedes configurar otra concurrencia positiva en el archivo de entorno externo. El aumento consume más memoria y puede solapar contenedores CAD.

El puente tiene un turno independiente para `codex-cli` y otro para `antigravity-cli`: una llamada de GPT y otra de Antigravity pueden avanzar simultáneamente. Dos solicitudes al mismo proveedor esperan su turno. Solo se vuelve a enviar una petición si el puente devuelve expresamente `409` con código `busy`, que garantiza que la llamada al modelo no empezó. Un timeout, error de conexión o error del proveedor no se reenvía automáticamente: su consumo podría ser incierto. La espera no agrega intentos experimentales.

Los cambios del trabajador se incorporan a su imagen al construirla. La concurrencia se aplica al recrear el trabajador; los cambios del puente se cargan al reiniciar su servicio. Haz esas operaciones cuando no haya trabajo activo. **No ejecutes `aplicacion.iniciar_trabajador` para añadir capacidad mientras otro trabajador está generando:** su recuperación de arranque marca ejecuciones interrumpidas y pausa campañas. Tampoco reinicies el puente durante una llamada.

Para habilitar una segunda campaña con un despliegue anterior todavía ocupado, se puede añadir un proceso auxiliar con el mismo entorno y los mismos volúmenes, pero otro socket de puente. Antes de mover la campaña se comprueba que todas sus ejecuciones estén pendientes y que solo exista una tarea reservada; se retira únicamente esa reserva con `revoke(..., terminate=False)`, confirmando la respuesta del trabajador, y se ejecuta la campaña en el auxiliar sin pasar por la recuperación global de arranque. Nunca se revoca ni termina la tarea activa. El auxiliar se elimina al finalizar su campaña. Esta transición se utilizó para activar GPT 5.6 Luna Max mientras Gemini 3.8 Flash High seguía ejecutándose; el trabajador y el puente originales no se reiniciaron.


## Reintentos operativos de NVIDIA

Las nuevas ejecuciones y campañas **open-loop y closed-loop** de NVIDIA fijan `protocolo_reintentos=ciel-nvidia-reintentos-v1` en su perfil. Un timeout de lectura, conexión o escritura, un error de transporte, HTTP 408/429/5xx o una respuesta vacía/malformada del endpoint hacen que se reintente **el mismo modelo, mensajes y parámetros**. Las esperas son 5, 10, 20, 40 y 60 segundos; después se mantienen en 60 segundos. Se respeta una espera mayor indicada por `Retry-After`. El timeout por petición crece desde el valor configurado, duplicándose hasta 900 segundos para dar tiempo a modelos lentos; también se registra por llamada. Se continúa hasta recibir una respuesta o cancelar la campaña. Los errores de credenciales, parámetros, modelo inexistente o rechazo explícito no se repiten: quedan como incidencia del proveedor.

Estos reintentos no crean otro intento CAD ni consumen las cinco iteraciones de closed-loop. Mientras se espera, la ejecución sigue `generando`, el intento indica `esperando_proveedor` y el mensaje muestra la causa y la siguiente espera. Se conservan fecha, modelo, código de incidencia, identificador de respuesta cuando existe y espera en `solicitud_modelo.reintentos_operativos`, visibles también en las exportaciones JSON y ZIP. Una falta de respuesta no se marca como código o CAD inválido y no entra en el denominador evaluable. Cuando llega código, la validación y el límite de uno/cinco intentos siguen funcionando normalmente.

Cada reenvío es una llamada operativa adicional; tras un timeout el consumo de la llamada anterior puede ser desconocido. Se registra esa incertidumbre sin asignarle cero tokens o costo. La cancelación se comprueba antes de otra llamada y durante la espera. Pausar conserva la regla existente de terminar la ejecución ya iniciada; no inicia el siguiente caso.

El protocolo queda congelado en las campañas nuevas. Las campañas históricas mantienen su política anterior, sus respaldos y sus resultados. Quality Loop oculto conserva su protocolo separado. No se reescriben resultados históricos para convertir fallos anteriores en éxitos.

El servicio `trabajador_nvidia` consume exclusivamente la cola `nvidia`, con un proceso. Las nuevas generaciones NVIDIA se envían a esa cola; los trabajos CLI y las campañas históricas mantienen la cola anterior. El trabajador NVIDIA arranca directamente Celery, sin ejecutar la recuperación global de `iniciar_trabajador`, para poder añadirlo sin marcar como interrumpidas campañas de otro trabajador.

Para actualizar esta función mientras una campaña CLI está activa, construye la imagen y recrea **solo API y trabajador NVIDIA**:

```bash
docker compose --env-file /ruta/externa/agente-ciel.env -f compose.yaml -f compose.suscripciones.yaml build api
docker compose --env-file /ruta/externa/agente-ciel.env -f compose.yaml -f compose.suscripciones.yaml up -d --no-deps api trabajador_nvidia
```

El trabajador CLI y el puente del escritorio continúan con sus procesos actuales. Las comprobaciones de regresión simulan NVIDIA; no consumen cuentas reales.

## Tres campañas simultáneas y sustitución del endpoint Kimi

Los servicios `trabajador` (cola general/Antigravity), `trabajador_codex` (cola `codex`) y `trabajador_nvidia` (cola `nvidia`) pueden procesar tres campañas simultáneamente. Las generaciones y campañas nuevas con GPT se envían a `codex`; las que incluyen un perfil nuevo NVIDIA siguen yendo a `nvidia`. Cada campaña mantiene el esfuerzo y el protocolo que congeló al crearse. Los trabajadores dedicados arrancan directamente Celery y no ejecutan la recuperación global que pausaría campañas de otros procesos.

Con `compose.suscripciones.yaml`, Codex utiliza un segundo puente en `CLI_PUENTE_DIRECTORIO/suscripciones-paralelo.sock`; el puente original conserva `suscripciones.sock`. Configura un segundo servicio local con los mismos parámetros de instalación, cambiando únicamente la ruta de `--socket`, o inícialo en otra terminal:

```bash
python -m aplicacion.puente_cli --socket /ruta/externa/puente/suscripciones-paralelo.sock
```

En este equipo ambos puentes están configurados con servicios de usuario; el auxiliar se habilitó para iniciar con la sesión. No es necesario reiniciar el puente original para añadir el auxiliar. Durante una campaña GPT activa no recrees `trabajador_codex`; para actualizar únicamente NVIDIA recrea `api trabajador_nvidia` con `--no-deps`.

El 21 de octubre de 2026, `moonshotai/kimi-k3` dejó de aparecer en el catálogo autenticado y su endpoint público devolvió HTTP 410. [NVIDIA lo identifica como endpoint público obsoleto](https://build.nvidia.com/moonshotai/kimi-k3?section=deploy). Ahora esa respuesta se clasifica como `endpoint_retirado`, queda como incidencia del proveedor y no se reintenta indefinidamente ni se sustituye el modelo silenciosamente. K3 continúa registrado para leer campañas y trazas históricas, pero no se ofrece para crear nuevas generaciones.

Se incorpora `moonshotai/kimi-k2.6`, disponible en el catálogo autenticado, como una identidad distinta. Sus límites fijados son 262.144 tokens de contexto compartido y 65.536 de salida, según la [ficha NVIDIA](https://docs.api.nvidia.com/nim/reference/moonshotai-kimi-k2-6) y su [API](https://docs.api.nvidia.com/nim/reference/moonshotai-kimi-k2-6-infer). La entrada no se recorta en la aplicación y la salida se configura con ese máximo. Elegirlo para sustituir una campaña K3 requiere crear una campaña nueva con el mismo conjunto, motores, modos, casos y semilla. La original y su diagnóstico 410 se conservan; no se atribuyen resultados K2.6 a K3.

La presencia en `GET /models` confirma una entrada de catálogo, **no que la cuenta pueda inferir con ese endpoint**. Si la generación devuelve HTTP 404 con `Function ... Not found for account`, se clasifica como `endpoint_no_habilitado` y se muestra un diagnóstico sin identificadores de cuenta. No se trata como timeout ni se cambia a otro modelo automáticamente. La disponibilidad o habilitación de esa función debe revisarse con NVIDIA. En la comprobación de este equipo, K2.6 apareció en el catálogo pero su llamada de generación devolvió ese 404; no se presenta como campaña ejecutándose con éxito.

## Recuperar una campaña bloqueada desde su intento guardado

Con los trabajadores libres para esa campaña y sin tareas activas o reservadas duplicadas, se puede ejecutar un auxiliar que recupera el bloqueo y después procesa los casos pendientes. No reinicia trabajadores ni puentes y no ejecuta la recuperación global del arranque:

```bash
docker compose --env-file /ruta/externa/agente-ciel.env -f compose.yaml -f compose.suscripciones.yaml run -d --no-deps --name recuperar-gpt trabajador_codex python -m aplicacion.reanudar_campana ID_CAMPANA
```

Para Antigravity se usa el servicio `trabajador`. Si el último intento terminó en `error_proveedor` sin respuesta ni código guardados, hace falta añadir `--repetir-proveedor`, después de que el investigador autorice otra llamada: el consumo anterior puede ser incierto. Si terminó en `error_supervisor` con respuesta guardada, se ejecuta ese código sin volver a consultar la IA. Otros bloqueos requieren revisión específica.

La recuperación comprueba plantilla, imágenes CAD y referencias congeladas. Conserva identificadores, mensajes de la solicitud, modelo, esfuerzo, resultados terminados y numeración de intentos. El intento recuperado registra su incidente anterior, duración, fecha, acción y posible consumo desconocido en `solicitud_modelo.recuperaciones_operativas`, con protocolo `ciel-recuperacion-explicita-v1`. Los fallos CAD posteriores mantienen el límite científico original de uno o cinco intentos. El auxiliar continúa con los pendientes y termina al completar, pausar o bloquear de nuevo la campaña; su contenedor se puede retirar una vez finalizado.
