# Validación nativa 0.6.0

- 34 pruebas unittest correctas en `ciel-libre-validacion:local`, con SQLite temporal y proveedores simulados, sin red. Las nueve pruebas de biblioteca cubren migración aditiva con copia consistente e idempotencia, consulta y filtros, exportaciones antiguas incompletas y hashes, colisiones, variantes independientes, selección de intentos y conservación del código e instrucciones en los cinco intentos.
- Las 25 pruebas anteriores de la edición libre, campañas e inicio manual siguen pasando. La primera ejecución tuvo seis errores por un montaje de pruebas que resolvía los datos en `/programa`; se corrigió el montaje para conservar la estructura de la edición y se repitió la suite completa satisfactoriamente.
- `npm --prefix edicion-libre/programa/interfaz run construir`: correcto. Se mantiene el aviso de tamaño del paquete de Three.js.
- Prueba del renderizador en `ciel-libre-evaluador:v1`: nueve PNG válidos (siete vistas, lámina y miniatura) desde una caja de dimensiones distintas. Perfil independiente `ciel-biblioteca-render-v1`; los perfiles históricos permanecen intactos.
- Revisión Playwright con API simulada: historial y formulario de variantes en tema claro de escritorio y oscuro a 390 px; sin desborde horizontal. Capturas en `output/playwright/ciel-060-*.png`.
- Instalador NSIS 0.6.0 compilado, con `programa.zip`, manifiesto y SHA-256. La entrega 0.5.1 se conserva.

No se ejecutaron inferencias, campañas reales, motores CAD ni el instalador en Windows. La instalación sobre los datos reales de 0.5.1 y la generación efectiva de una variante deben comprobarse en el Windows de destino. Las pruebas de migración usan una SQLite histórica representativa; no se accedió a los datos del equipo Windows del usuario.

Los trabajos individuales pendientes en la cola en memoria quedan bloqueados al reiniciar, con explicación visible; las campañas mantienen su control manual. Se pueden crear nuevas variantes desde los resultados válidos conservados.
