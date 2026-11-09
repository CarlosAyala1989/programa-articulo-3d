# Validación nativa 0.6.2

## Correcciones

- `ejecucion_actual` selecciona únicamente filas `generando`. Las bloqueadas antiguas siguen contándose y conservan su evidencia, pero ya no fijan el enlace Ver ejecución al reanudar y avanzar la campaña.
- La interfaz publica el resumen antes de consultar métricas y actualiza el estado de la campaña en el selector. Las consultas periódicas no se superponen; el fallo de métricas no congela el resumen.
- El modo Preparar del instalador rechaza una instancia abierta en lugar de abrirla y devolver éxito sin extraer la nueva versión. El modo Abrir conserva su comportamiento de reutilizar la instancia existente. También se avisa si otra ventana mantiene el mutex de preparación.
- HTML de entrada servido con Cache-Control no-store. La API de opciones informa version_aplicacion para diagnóstico.
- Incluye el selector principal de campaña de 0.6.1. No modifica protocolos, campañas ni ejecuciones históricas.

## Validación

- 37 pruebas unittest correctas en `ciel-libre-validacion:local`, sin red, con SQLite temporal y proveedores/CAD simulados. Tres regresiones nuevas verifican prioridad de la generación activa frente a bloqueadas anteriores, cambio de enlace al pasar a otra ejecución tras pausa, y ausencia de ejecución activa cuando solo hay bloqueadas.
- Construcción Vite correcta, con el aviso existente de tamaño de Three.js.
- Sintaxis de preparar.ps1 validada con el parser de PowerShell 7.4.
- Playwright con API simulada: Ver ejecución cambia de activa-a a activa-b al actualizar, incluso con respuestas 503 de métricas. Tema claro de escritorio y oscuro móvil a 390 px, sin desborde horizontal. Capturas en `output/playwright/ciel-062-ejecucion-activa-*.png`.
- Instalador NSIS 0.6.2 compilado y entrega con hashes SHA-256. Se conservan las entregas anteriores.

No se ejecutaron inferencias ni campañas reales, ni se instaló en el Windows del usuario. La actualización efectiva y el control de una instancia abierta deben comprobarse allí. Para actualizar: pausar, esperar a que termine la ejecución en curso y cerrar la aplicación y la consola/preparación, no solamente la pestaña. Ejecutar el instalador con el mismo usuario y comprobar v0.6.2 en la cabecera; Ctrl+F5 si persiste una página anterior.
