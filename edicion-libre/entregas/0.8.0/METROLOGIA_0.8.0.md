# Comparar la impresión manual con el modelo virtual — 0.8.0

El estudio utiliza los 45 prompts aprobados por la dirección. El conjunto congelado de 60 y las campañas históricas siguen disponibles. La aplicación no envía piezas a la impresora.

## Actualizar Windows

Pausa las campañas, cierra Agente Ciel y su consola. Ejecuta `Agente-Ciel-Nativo-0.8.0-Setup.exe` con el mismo usuario de Windows y abre el acceso directo. La cabecera debe indicar v0.8.0. Conserva los resultados anteriores; antes de añadir las tablas de perfiles y planes se respalda SQLite. Los entornos y protocolos CAD existentes no cambian. La instalación 0.7.0 ya fue confirmada por el usuario; la actualización 0.8.0 se compiló desde Linux y debe comprobarse en Windows.

## Preparar una vez y reutilizar

1. Abre un trabajo exitoso en **Resultados → Comparar resultado**.
2. En **Impresión, escaneo y calibración**, registra impresora, material y parámetros del laminador. En **Configuración reutilizable**, guarda un perfil. El más reciente se carga al abrir otra pieza. Puedes cambiar los parámetros antes de comparar. Cada guardado crea un perfil nuevo y no altera mediciones anteriores.
3. En **Cotas automáticas del escaneo**, pulsa **Detectar cotas del modelo**. Selecciona los diámetros y separaciones entre planos relevantes para la investigación y guarda la selección. Cada cota muestra un código y su ubicación en las coordenadas del modelo virtual: centro XYZ y eje en cilindros, o eje y posiciones de caras en planos. La tabla de resultados conserva la ubicación del plan utilizado. Quedan vinculados al hash del STL. Si omites este paso, al subir el primer escaneo se detectan y usan todas las cotas compatibles.
4. Para las siguientes réplicas elige el archivo del Otter y compara. Revisa siempre la superposición y confirma la alineación. Si cambias unidades, impresora, material o parámetros, actualízalos antes de comparar.

## Adquirir la evidencia física

Imprime manualmente, calibra el Otter según su procedimiento y exporta solo la pieza desde CrealityScan como STL/OBJ/PLY, sin mesa ni soportes. También se aceptan PCD sin compresión, ASC y XYZ. Declara las unidades reales; ICP no aplica escala para esconder una contracción. Registra la fecha/calibración de ese escaneo. Adjunta una foto si necesitas la matriz fotográfica del PDF; el software no puede crear una fotografía experimental de la impresión.

## Qué mide automáticamente

- **Diámetros:** detecta paredes cilíndricas completas del STL nominal. En mallas ajusta robustamente los vértices de las paredes laterales; en nubes usa los puntos de la banda local, evitando los extremos. Exige cobertura angular de 270° y un mínimo de puntos. El eje se fija al nominal después del registro global: no es una medición de coaxialidad ni un ajuste libre de orientación del cilindro.
- **Espesores/separaciones:** ajusta dos planos en las regiones nominales y evalúa su separación en una referencia local común. Exige al menos 40 puntos por plano y cobertura de área del 25 %. La banda se limita para no mezclar los dos planos opuestos.
- **ΔD:** medida menos nominal. Su media y desviación estándar se calculan entre las cotas válidas de esa pieza. Se informa cuántas cotas se planificaron y cuántas se midieron. Una única cota deja la desviación estándar vacía. El residuo del ajuste está separado y no estima repetibilidad, incertidumbre ni calibración del escáner.

Las cotas nominales se extraen del STL, con el error de teselación correspondiente. Las roscas, dientes individuales, conos, superficies libres o cilindros incompletos necesitan un plan específico o medidas complementarias. La selección automática identifica geometría; debes comprobar que las cotas escogidas representan las cotas críticas del experimento.

La **banda de asociación** es el entorno alrededor de cada región nominal donde se buscan puntos del escaneo. Si una deformación queda fuera, la cota aparece sin cobertura: amplía la banda solo tras revisar las superficies vecinas. Un ajuste con pocos puntos, cobertura angular/área insuficiente o residuo excesivo no publica una medida. Una región vecina dentro de la banda puede contaminar un ajuste; revisa selección y resultado.

## Hausdorff y exportaciones

En el protocolo v2, `hausdorff_maximo_mm` es el Hausdorff discreto simétrico exacto entre todos los vértices/puntos importados, después del registro rígido. No recorta valores atípicos ni toma una muestra para este máximo. Depende de la densidad de los dos conjuntos: no debe interpretarse por sí solo como error continuo entre superficies.

Se conserva por separado `hausdorff_superficie_muestreado_mm`: máximo bidireccional de muestras a triángulos (o a puntos si se utiliza una nube). P95, Chamfer y mapas también usan muestreo determinista. No se certifica el máximo continuo de dos superficies. Las comparaciones antiguas v1 conservan su definición y protocolo; un reintento no las convierte a v2.

La descarga incluye originales y hashes, configuración completa, plan de cotas, resultados JSON, cotas CSV, distancias muestreadas, transformación, mapa PNG y PLY con colores. Los CSV de campaña incluyen alcance de Hausdorff, cobertura de cotas, ΔD y dispersión. Los informes no sustituyen valores ausentes por cero.

## Ensayos de desarrollo

`pruebas/datos/placa_publica/origen.json` identifica el STL público, commit, licencia MIT y SHA-256. Se usa una copia centrada y escalada a 1:4 (50,8 × 76,2 × 3,175 mm) para representar una pieza pequeña. Los ensayos de contracción, espesor y diámetro son controles sintéticos con valores conocidos; no cuentan como escaneos del Otter ni como resultados de manufactura.
