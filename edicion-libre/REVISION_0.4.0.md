# Revisión estática de Agente Ciel Nativo 0.4.0

## Artefacto

- Instalador: `dist-nativo/Agente-Ciel-Nativo-0.4.0-Setup.exe`.
- Tamaño: 469,995 bytes.
- SHA-256: `e505c3848c64d8c04450f494effdda3d5899b2cb0d89b6ec1c0fb3f80c24049b`.
- Cabecera ejecutable Windows PE presente. Compilación NSIS completada.
- SHA-256 del paquete incluido coincide con `paquete.json`.
- 44 archivos de programa incluidos: backend, supervisor y motores nativos, evaluador, datos y frontend compilado.
- Sintaxis Python inspeccionada mediante AST; JSON leído estáticamente.
- Perfiles: cinco etiquetas exactas del usuario; Gemma Q8_0.
- Matriz preservada en el código: 45 × 5 × 3 × 2 = 1.350 ejecuciones, hasta 4.050 generaciones.
- Empaquetado sin pesos de modelos, bases de datos, archivos `.env`, dependencias Docker ni colas externas.

## Alcance de la revisión

**No se ejecutó la aplicación, ni modelos, ni motores CAD, ni pruebas del benchmark en Ubuntu para esta versión.** Solamente se editaron archivos, se inspeccionó su contenido y se compiló el instalador con el compilador NSIS. No se instalaron bibliotecas CAD ni runtimes Windows en Ubuntu.

El arranque, la instalación de ruedas nativas y las 1.350 ejecuciones deben comprobarse en el Windows de destino. Esta revisión no acredita funcionamiento observado en Windows. Las validaciones de la versión Docker 0.3.0 no se atribuyen a esta edición.

El instalador comprueba Ollama y sus etiquetas/cuantizaciones antes de preparar bibliotecas, verifica SHA-256 de Python/FreeCAD y del paquete, muestra errores completos y comprueba que la API nativa responda al iniciar. Estas comprobaciones se realizan al ejecutarlo en Windows.

## Datos y límites

SQLite activo en `%LOCALAPPDATA%\AgenteCielNativo\datos\ciel.sqlite`; resultados CSV/JSON/geometrías y copias SQLite en `Documentos\CielLibre\Resultados`. Checkpoint experimental y métricas técnicas permanecen separados de fidelidad y metrología física. Los Job Objects limitan recursos y terminación de procesos; no restringen permisos de archivos/red.

Los requisitos físicos del PDF necesitan datos de impresión, escaneo y medición reales. Se incluye una plantilla sin valores inventados. IoU necesita una referencia independiente y autorización explícita mediante el indicador correspondiente. Los 45 prompts permanecen como piloto.
