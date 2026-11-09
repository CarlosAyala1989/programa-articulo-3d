# Validación nativa 0.5.1

- 25 pruebas unittest correctas en `ciel-libre-validacion:local`, con SQLite temporal y proveedores/CAD simulados, sin red. Incluyen etiquetas distintas, siete modelos instalados, Ollama cerrado, identidad de variantes, configuración y verificación de un modelo adicional, selección parcial, guardado en borrador y reinicio sin programar campañas.
- `npm ci` en una carpeta temporal con el lockfile de la edición y `npm --prefix edicion-libre/programa/interfaz run construir`: correctos. Se desactiva el análisis de eliminación de código de Rollup porque agotaba memoria también con la interfaz anterior; la construcción termina en aproximadamente un segundo. El JS minificado mide 739 kB (201 kB gzip); Vite mantiene su aviso de tamaño.
- Sintaxis de `nativo/preparar.ps1` validada con el parser de PowerShell 7.4.
- Revisión Playwright de la interfaz estática con respuestas API simuladas: selección de un modelo adicional, CadQuery, open-loop y los 45 prompts produce una vista previa de 45 ejecuciones. Guardar queda habilitado sin iniciar trabajos. Capturas en `output/playwright/ciel-manual-*.png`, temas claro/oscuro y anchos 1440/390; sin desborde horizontal móvil.
- Instalador NSIS generado en `entregas/0.5.1`, con ZIP, manifiesto y SHA-256 verificados. La entrega 0.5.0 se conserva.

No se ejecutaron inferencias, motores CAD, campañas reales ni el instalador Windows en Linux. Falta comprobar la instalación y generación reales en el Windows de destino. Python 3.14 del usuario se conserva: los entornos CAD siguen usando el Python 3.11 preparado por el instalador.
