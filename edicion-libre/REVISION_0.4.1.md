# Corrección del instalador nativo 0.4.1

## Causa y cambio

El registro del Windows del usuario identifica `UnsupportedCompressionMethodError`: FreeCAD 1.1.3 usa BCJ2, que `py7zr` no admite. Se reemplazó la extracción por `7zr.exe` oficial de 7-Zip 26.04, incluido sin instalar software global. El código oficial de Alone7z incluye Bcj2Coder/Bcj2Register.

- Extractor: SHA256 `256feca8e274e5da655e2a284fabafd9f554365eb164862089dacd4e8276d282`, comprobado contra el digest del asset oficial de GitHub.
- Se reutiliza la descarga portable de FreeCAD después de comprobar su SHA256.
- Se extrae primero en un directorio temporal; solo después del código de salida cero y presencia de los ejecutables se publica y escribe el marcador de extracción completa.
- Una carpeta parcial de 0.4.0 se repara aun si contiene FreeCAD.exe y python.exe.
- Se preservan entornos, modelos, SQLite y resultados. La dependencia py7zr se retira de requirements-api; pip conserva los paquetes existentes que satisfacen los requisitos.
- La reanudación con tres entornos ya preparados necesita 3 GB adicionales, frente a 15 GB de la preparación inicial, más espacio para resultados.
- El protocolo, los cinco modelos, las versiones CAD y la matriz de 1.350 ejecuciones se mantienen.

## Artefacto e inspección estática

Instalador: `dist-nativo/Agente-Ciel-Nativo-0.4.1-Setup.exe`. Tamaño: 770741 bytes. SHA256: `94bf03c7d284b1091e237bb966d8b929a3406f5142b2ef5af3ce35d67a67c041`.

Compilación NSIS completada, cabecera Windows PE presente, SHA256 del ZIP coincide con paquete.json y Python incluido inspeccionado mediante AST. El paquete contiene el extractor actualizado y metadatos de versión 0.4.1. Se incluyen la licencia LGPL y referencia al código fuente de 7-Zip.

No se ejecutaron el extractor Windows, la aplicación, los motores, modelos ni el benchmark en Ubuntu. El resultado real de la extracción y el arranque deben comprobarse en el Windows de destino. Esta inspección no se presenta como prueba funcional de Windows.

## Fuentes

- Limitación de py7zr: https://py7zr.readthedocs.io/en/latest/_modules/py7zr/compressor.html
- Distribución oficial: https://www.7-zip.org/download.html
- Asset y digest: https://api.github.com/repos/ip7z/7zip/releases/tags/26.04
- BCJ2 en el extractor: https://github.com/ip7z/7zip/blob/26.04/CPP/7zip/Bundles/Alone7z/makefile
