# Validación de Agente Ciel Libre 0.3.0

Fecha: 13 de octubre de 2026. Entorno: Linux con Docker Engine y PowerShell 7.4.

## Artefacto

- Archivo: `dist/Agente-Ciel-Libre-0.3.0-Setup.exe`.
- Tamaño: 308,140 bytes.
- SHA-256: `f973531fef2866815fb6a4fe4073e2e084b16b0010af536e7172455539c122b7`.
- Compilación NSIS completada; formato PE de Windows e integridad SHA-256 correctos.
- El ZIP del programa se verificó y no incluye `modelos_instalados.json`: actualizar el programa conserva el checkpoint de los modelos.
- El instalador incluye los scripts PowerShell nativos y omite los scripts WSL de las versiones anteriores.

## Comprobaciones realizadas

| Comprobación | Resultado |
| --- | --- |
| Compilación del frontend y de las seis imágenes Docker | Correcta |
| 19 pruebas Python en la imagen nueva de la aplicación | Correctas |
| 9 pruebas de las funciones PowerShell | Correctas |
| Sintaxis del arranque PowerShell y sus funciones | Correcta |
| Errores con caracteres NUL y stderr nativo | Mensaje completo y código de salida conservados |
| Argumentos y carpetas con espacios | Correctos en las pruebas PowerShell |
| Docker Desktop Linux, kernel de Hyper-V simulado | Aceptado |
| Kernel WSL, contenedores Windows y motor remoto simulados | Rechazados con explicación |
| Descarga corrupta y descarga parcial ya completada | Rechazo y recuperación correctos |
| Importación interrumpida en L03 | Reanuda sin volver a importar L01 y L02 |
| Cuantizaciones, digest, licencia y registro de cinco modelos | Verificados con respuestas simuladas |
| API en proyecto Docker temporal | Disponible, edición libre y cinco modelos |
| Conexión a `host.docker.internal:11434` | Verificada mediante alias de red y Ollama simulado |
| CadQuery: cubo de 20 mm | STEP/STL verificados; 8.000 mm³ |
| build123d: cubo de 20 mm | STEP/STL verificados; 8.000 mm³ |
| FreeCAD: cubo de 20 mm | STEP/STL verificados; 8.000 mm³; también exporta FCStd |
| Limpieza del entorno de integración | Contenedores, red, volúmenes y archivos temporales retirados |

El servidor Ollama simulado rechaza las solicitudes POST. No se descargaron pesos ni se ejecutaron inferencias o llamadas a proveedores de pago durante estas comprobaciones.

## Límite de esta validación

No hubo una computadora Windows disponible. Estas comprobaciones no certifican la ejecución del instalador en Windows PowerShell 5.1, el acceso real desde Docker Desktop Hyper-V a Ollama Windows, ni la importación de los GGUF completos en el servidor Windows. El código usa PowerShell compatible con 5.1 y comprueba los requisitos y la conexión antes de iniciar el trabajador, pero la instalación completa debe comprobarse en Windows.

Para funcionar sin WSL, Docker Desktop debe ejecutar contenedores Linux con Hyper-V; se necesitan la edición compatible de Windows, la virtualización activa y memoria asignada suficiente. Ollama debe estar abierto en el puerto 11434. Los errores quedan en `registros/` y `ultimo-error.txt` dentro de la carpeta de instalación.
