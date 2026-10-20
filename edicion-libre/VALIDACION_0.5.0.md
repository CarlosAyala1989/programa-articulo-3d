# Publicación de Agente Ciel Libre 0.5.0

La incorporación al repositorio conserva el programa existente y separa su versión de la aplicación de pago. El instalador nativo se reconstruyó a partir del frontend compilado y las fuentes incluidas en esta entrega. Los hashes y los metadatos verificables están en `entregas/0.5.0/`.

Comprobaciones de esta publicación:

- 19 pruebas de aplicación libre y lote automático aprobadas, con Ollama y CAD simulados, sin conexión a modelos reales. También se ejecutaron sobre una exportación del código ya confirmado en Git, sin depender de archivos locales ignorados.
- Frontend de producción compilado con Vite; se conserva el aviso sobre tamaño de un bundle.
- Instalador Windows compilado mediante NSIS en un contenedor sin red. Tamaño: 772.645 bytes.
- Paquete del programa: 319.520 bytes; integridad ZIP y hashes verificados.
- Tres pruebas de publicación aprobadas: coherencia de versiones, integridad de la entrega y hash/licencias del extractor.
- Sintaxis Python y JSON revisados. Sin pesos de modelos, credenciales, bases de datos, resultados ni dependencias node_modules en los archivos publicados.
- Prompts, plantillas y licencias originales conservados literalmente, incluidos sus espacios cuando forman parte de los activos fijados por hash.

Para repetir las comprobaciones:

```bash
docker run --rm --network none \
  -v "$PWD/edicion-libre/programa:/servicio:ro" \
  -v "$PWD/edicion-libre/pruebas:/pruebas:ro" \
  -e URL_BASE_DATOS=sqlite:// \
  ciel-libre-validacion:local python -m unittest discover -s /pruebas -v
python -m unittest discover -s edicion-libre/pruebas_versionado -v
```

La imagen de pruebas se construye con `instalador/Dockerfile.validacion`, como explica el README. Estas comprobaciones no ejecutan el instalador, los motores nativos ni el benchmark en Windows. La validación funcional de Windows sigue pendiente y no se atribuyen a esta edición las pruebas CAD de la edición Docker.
