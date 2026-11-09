# Validación nativa 0.6.1

Historial presenta Campaña como filtro principal a todo el ancho, mediante el listado existente de campañas guardadas. Prompt, librería, modelo y estado quedan agrupados debajo. Cambiar de campaña limpia los filtros secundarios y reinicia la paginación. La opción Todas conserva el acceso a los trabajos individuales. No cambia el esquema ni los resultados históricos.

- Playwright con API simulada: campaña seleccionada y librería se envían juntas en la consulta; cambiar campaña limpia prompt y reinicia paginación. Capturas en `output/playwright/ciel-061-campana-*.png`, escritorio claro y móvil oscuro a 390 px, sin desborde horizontal.
- Construcción Vite correcta; se mantiene el aviso de tamaño de Three.js.
- Instalador NSIS 0.6.1 compilado. Entrega con ZIP de programa, manifiesto y SHA-256; se conserva la entrega 0.6.0.
- La instalación efectiva en Windows queda pendiente de comprobar en el equipo de destino.
