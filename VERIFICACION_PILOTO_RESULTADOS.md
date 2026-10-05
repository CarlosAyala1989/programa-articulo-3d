# Verificación del piloto frente a los resultados esperados

Fecha: 4 de octubre de 2026. Alcance: únicamente el programa ya construido para generar y corregir hasta cinco veces con DeepSeek y producir piezas en CadQuery, build123d y FreeCAD Python API. La fuente de criterios es `Requisitos_Resultados-CADLLMIA.pdf`, interpretada con las definiciones de la sección 12 de `PLAN_TECNICO_AGENTE_CIEL.md`. Esta verificación **no** es el benchmark de 60 prompts ni un resultado de manufactura o metrología.

## Prueba funcional comparable

Se envió a los tres motores, con `deepseek-flash`, una misma descripción: bloque de 40 × 30 × 10 mm centrado en el origen, con un agujero cilíndrico pasante de diámetro 8 mm centrado y paralelo a Z, sin chaflanes ni redondeos. El volumen nominal analítico es **11 497,345175 mm³**. Cada motor recibió una generación independiente; no se tradujo el script de otro motor.

| Motor | Ejecución | Intentos y desenlace | STEP: sólido válido / volumen [mm³] | STL: watertight / DangEL / Euler | Dimensiones STL [mm] | Archivos |
|---|---|---|---|---|---|---|
| CadQuery | `1cef6df5-4a36-42e0-bad5-be83f19cb920` | 1; éxito | Sí, uno / 11 497,345175 | Sí / 0 / 0 | 40 × 30 × 10 | STL, STEP, script |
| build123d | `a27643f4-509a-47ea-a859-b4db780ffc6f` | 2; primer intento con `TypeError` por usar `radio` como argumento de `Cylinder`; corrección exitosa | Sí, uno / 11 497,345175 | Sí / 0 / 0 | 40 × 30 × 10 | STL, STEP, script |
| FreeCAD Python API | `0f29e54d-b645-46de-bc92-fd5527a5d352` | 1; éxito | Sí, uno / 11 497,345175 | Sí / 0 / 0 | 40 × 30 × 10 | STL, STEP, FCStd, script |

Los tres STL tienen 520 triángulos; los vértices del agujero medidos en XY tienen radio 4 mm. El volumen de la malla teselada es 11 497,553 mm³, **0,0018 %** por encima del volumen analítico. Esta diferencia corresponde a la aproximación poligonal del STL; el STEP conserva el volumen nominal en esta prueba. Se reimportaron los tres STEP mediante OpenCascade/CadQuery y se comprobaron validez, un único sólido y volumen. Trimesh 5.1.1, ejecutado **fuera de la aplicación**, comprobó watertight y contó como DangEL las aristas cuya incidencia no es dos. Se verificó que el tamaño y SHA-256 de todos los archivos descargados coinciden con los metadatos de la API. El ejecutor FreeCAD también reabre el FCStd antes de aceptar el resultado.

Se verificó además que `deepseek-v4-pro` completó una ejecución real con FreeCAD (`49ae3920-f74a-4f30-a08c-def4d1fface9`). Con proveedor simulado se comprobó un rescate en el segundo intento y una ejecución que agotó **exactamente cinco** intentos sin publicar archivos. Los cinco servicios Docker permanecen en ejecución y `/api/salud` responde correctamente.

## Cumplimiento del alcance construido

| Criterio del piloto | Estado | Evidencia y límite |
|---|---|---|
| Selección de Flash/Pro y de los tres motores | Cumple | La API ofrece ambas opciones; hubo inferencia real con los dos modelos y archivos válidos de los tres motores. |
| Generación propia por motor | Cumple en la prueba | Cada solicitud selecciona un único motor y el script usa su API; los STEP del requisito común se reimportaron satisfactoriamente. |
| Corrección con máximo de cinco generaciones totales | Cumple | El fallo real de build123d fue corregido en el segundo intento; las pruebas controladas confirmaron rescate y límite de cinco. |
| Sólido B-Rep exportable | Cumple en las piezas probadas | El ejecutor exige un sólido válido y volumen positivo. Las tres salidas de la prueba común se reimportaron como STEP válidos. Esto no demuestra fidelidad universal al prompt. |
| STL, STEP, script y FCStd de FreeCAD descargables | Cumple | Archivos descargados e integridad SHA-256 comprobada. FCStd se reabre y conserva un sólido. Esto no demuestra historial paramétrico editable. |
| Historial de intentos, diagnóstico, duración agregada y tokens por ejecución | Parcial | Se guardan y consultan en JSON mediante la API. No hay exportación CSV/JSON de campaña ni separación de latencia IA, ejecución CAD y exportación. |
| Watertight y DangEL | Solo comprobación externa puntual | Las tres mallas de esta prueba son watertight y tienen DangEL = 0. La aplicación no ejecuta Trimesh ni persiste estas métricas, así que todavía podría aceptar un STL topológicamente defectuoso. |

## Métricas del documento de resultados que aún no se pueden declarar

1. **Compile Rate y gráfico acumulado por iteración.** Hay historial de intentos, pero no un campo separado que distinga «el script terminó sin excepción» de «el sólido CAD es válido». El estado `invalido` reúne error sintáctico, excepción en ejecución y resultado geométrico inválido. Tampoco existe un modo open-loop independiente ni un dataset/campaña con denominador congelado. La reparación observada prueba el mecanismo, pero no cuantifica su mejora poblacional.
2. **Invalidity Ratio de campaña.** El estado final permitiría contar éxitos y fallos CAD de un conjunto definido, pero aún faltan campaña, dificultad, elegibilidad y clasificación de incidencias para un denominador defendible. Las ejecuciones de prueba ya existentes no deben mezclarse con los 60 casos finales.
3. **Volumetric IoU y fidelidad geométrica general.** La prueba analítica verifica volumen, dimensiones y agujero de una pieza conocida. El programa aún no registra ground truth ni calcula IoU. Un sólido válido pero geométricamente equivocado podría quedar marcado como `completada`.
4. **Porcentaje watertight y DangEL de campaña.** Se calcularon externamente solo para la prueba común. Falta integrar y guardar el análisis de cada STL final con cobertura y denominador.
5. **Comparación entre las tres bibliotecas.** La generación de archivos ya funciona, pero no hay matriz de condiciones, 60 prompts balanceados 20/20/20, repeticiones ni resultados por nivel. Con un solo requisito común no procede publicar tasas o superioridad de un motor.
6. **Trazabilidad experimental completa.** Se conservan descripción, código, intentos, tokens, archivos y hashes. Todavía no se guarda por ejecución el prompt de sistema íntegro y su versión, digest de imagen, versión efectiva del motor, parámetros de teselación y un manifiesto de campaña.

La fabricación, fotografía, escaneo, ICP, Hausdorff físico, Chamfer físico, error dimensional y mapas de calor pertenecen a hitos posteriores y **no forman parte de esta evaluación del piloto**. Los resultados actuales acreditan la integración de generación y exportación para un caso conocido; no acreditan todavía los resultados cuantitativos de las secciones 4.1–4.3 del artículo.
