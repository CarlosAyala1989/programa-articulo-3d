# Revisión estática de la corrección 0.4.2

## Error informado

El extractor encontró FreeCAD en `FreeCAD_1.1.3-Windows-x86_64-py311/bin`, pero la preparación pasó la carpeta principal al fijador de runtimes, que buscó `python.exe` fuera de bin. Las dos búsquedas anteriores aceptaban el primer `FreeCAD.exe` sin comprobar su intérprete hermano.

## Corrección

- Función PowerShell `Encontrar-FreecadBin`: solo devuelve una carpeta con `FreeCAD.exe` y `python.exe` juntos.
- La preparación comprueba el intérprete y muestra la ruta seleccionada antes de invocar el fijador.
- El fijador Python acepta carpeta portable o bin y resuelve la carpeta válida antes de construir las rutas del manifiesto.
- PYTHONUTF8/PYTHONIOENCODING se configuran antes de las invocaciones de Python para la salida UTF-8.
- Se reutilizan extracción verificada, entornos, modelos y datos. No cambian las versiones CAD, límites del ejecutor ni protocolo de 1.350 ejecuciones.

## Artefacto

`dist-nativo/Agente-Ciel-Nativo-0.4.2-Setup.exe`; 771421 bytes; SHA256 `bc2215227362b2fe2f50efd1e87f68b1adc9888ab14554b789caab90b260b595`.

Compilación NSIS completada. Cabecera PE, SHA256 del paquete y presencia de la corrección inspeccionados. Sintaxis Python revisada mediante AST sin importar módulos. No se ejecutaron preparación Windows, FreeCAD, aplicación, modelos ni benchmark en Ubuntu. La comprobación funcional sigue correspondiendo al Windows de destino.
