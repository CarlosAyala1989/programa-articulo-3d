# Auditoría del prompt maestro de mejoras

Estado de `prompt-maestro-mejoras.txt` tras la revisión del Quality Loop v2. **Implementado** significa que existe código y una prueba reproducible; no equivale a demostrar fidelidad geométrica universal. El conjunto `CAD-LLMIA-60` y los bucles históricos siguen separados.

| Apartado | Estado | Hito de la guía | Evidencia o límite |
|---|---|---:|---|
| Obligación inicial, compatibilidad y dataset | Implementado | 1 | README, código y pruebas revisados antes de editar; 60 casos sin cambios; `open-loop` y `closed-loop` conservados. |
| 1. GeometricPlan | Implementado | 2 | `aplicacion/calidad/modelos.py`; procedencia de cotas, IDs y referencias validados. |
| 2. Planner y Modeler separados | Implementado | 3 | `RouterModelos.planificar` y `flujo._mensajes_modelador`; plan persistido antes de modelar. |
| 3. Prompts especializados | Implementado | 4 | Perfiles mecánico, orgánico e híbrido en `aplicacion/calidad/prompts.py`. |
| 4. Recipes y sesgo de loft | Parcial | 4 y 14 | Quality Loop ya no inyecta el ejemplo de loft en cada caso y selecciona orientaciones de API por operación/motor; falta probar cada recipe compleja en los tres runtimes. |
| 5. Tres motores aislados | Implementado | 1 y 14 | CadQuery, build123d y FreeCAD producen STEP/STL mediante el supervisor; FreeCAD también FCStd. Smoke real de los tres. |
| 6. OCP controlado | Parcial | 4 y 14 | Allowlist de módulos/símbolos y AST en `aplicacion/generacion.py`; faltan fixtures ejecutables para BSpline surface, sewing y transformaciones avanzadas. |
| 7. Éxito técnico frente a calidad | Implementado | 8 | `technical_success` y `quality_success` separados en persistencia, API y UI. |
| 8. Quality Gate | Implementado | 8 | Pesos por clase, umbral, revisiones obligatorias y estados de ausencia en `aplicacion/calidad/metricas.py`. |
| 9. Métricas digitales | Implementado | 7 | IoU, Chamfer, caja, centroide, área, Hausdorff P95/P99, normales, simetría, silueta y metadatos versionados. Las métricas de referencia requieren habilitación. |
| 10. Referencias independientes | Implementado | 8 | El STEP de referencia solo se lee en `evaluador/`; el protocolo con métricas derivadas se etiqueta aparte. |
| 11. Ocho vistas digitales | Implementado | 9 | `evaluador/renderizado.py`; cámaras reproducibles y frente alineado al GeometricPlan, perfil v2. |
| 12. Proveedor NVIDIA | Implementado | 5 | Cliente NIM con clave de entorno, timeout, trazas y sin reintento automático. |
| 13. Modelos y roles | Implementado con excepción opcional | 5 y 10 | IDs y rutas requeridas configuradas; Cosmos permanece desactivado porque no apareció en el catálogo de esta clave. |
| 14. Model Router | Implementado | 5 | Nemotron Ultra/Super, Laguna, Kimi, GLM opcional y generador seleccionable; rutas configurables por entorno. Super es el juez textual predeterminado y puede recuperar un plan inválido ya completado de Ultra. |
| 15. Code Reviewer obligatorio | Implementado | 6 | AST → Laguna → runtime; Laguna recibe contrato y versión exacta del motor. |
| 16. Geometric Critic | Implementado | 8 | Informe Pydantic con errores, prioridades y preservación; el score lo calcula el Gate de forma determinista. |
| 17. Determinismo antes de LLM | Implementado | 7 y 8 | Cotas, volumen, centroide, topología y agujeros cilíndricos medidos en B-Rep/STL. |
| 18. Repairer | Implementado | 11 | Recibe plan, código padre, incidencias, métricas, crítica y `preserve`; prueba de reparación aceptada. |
| 19. Best-of-N | Implementado | 12 | Tres candidatos opcionales, IDs separados, evaluación, ranking y reparación desde el ganador. |
| 20. Presupuesto | Implementado | 11 | Topes de ciclos, llamadas y tokens presupuestados; costo monetario NVIDIA queda desconocido sin tarifa verificable. |
| 21–23. Reglas orgánicas, mecánicas e híbridas | Implementado como estrategia | 4 | Prompts y recipes diferenciados. La mejora de fidelidad en objetos difíciles aún necesita estudio experimental. |
| 24. Feature verification | Implementado con alcance explícito | 7 | Agujeros cilíndricos: cantidad, diámetro, eje/posición cuando se declaran; otros rasgos llevan `verification_status=unsupported` y juicio visual separado. |
| 25. Visual Review | Implementado | 10 | Kimi recibe lámina rotulada y métricas; comprobada conectividad mínima con imagen. |
| 26–30. Cinco prompts de rol | Implementado | 3, 6, 8, 10 y 11 | Planner, Modeler, Critic, Code Reviewer y Repairer diferenciados. |
| 31. Seguridad | Implementado para el alcance actual | 1 y 14 | AST, allowlist OCP, bloqueo de E/S generada y contenedores CAD sin red, sin root y con límites. |
| 32–34. Pruebas y mocks | Implementado | 14 | Unitarias con proveedores simulados, regresiones geométricas en imagen evaluadora; IA real no corre en la suite. |
| 35. Persistencia y trazabilidad | Implementado | 2 y 14 | `InformeCalidad`, plan, revisiones, candidatos, ranking, uso y protocolo; migración aditiva en `base_datos.py`. |
| 36. Interfaz | Implementado | 13 | Plan, validación técnica, incidencias de código, métricas, lámina/revisión visual, Gate, reparación y ranking. |
| 37–39. Entorno, API y JSON | Implementado | 5 | Configuración por variables; HTTP encapsulado; Pydantic y rechazo de JSON inválido. |
| 40. Fallos del reviewer | Implementado | 6 y 11 | `provider_error`, `timeout`, `malformed_response`, `review_rejected` y `geometry_rejected` diferenciados. |
| 41–43. Costos, comparabilidad y no contaminación | Implementado | 5, 8 y 12 | Llamadas acotadas, condición Best-of-N explícita, referencias segregadas y sin claves en frontend/BD. |
| 44. Aceptación completa | Parcial | 14 | Pasan suites y runtimes; falta un Quality Loop de extremo a extremo con inferencia real para cada clase y motor. |
| 45. Demostraciones A–D | Parcial | 14 | A/B/C/D cubiertos con pruebas controladas y caso CAD real de agujeros faltantes; falta reproducirlos con modelos reales. |
| 46–47. Documentación y límites | Implementado | 15 | README y esta auditoría separan resultados digitales de certificación física; no hay escaneo ni impresión. |
| 48–50. Secuencia y principio final | Parcial | 14 y 15 | Arquitectura y verificación implementadas; no se afirma fidelidad general sin la validación experimental pendiente. |

## Trabajo pendiente verificable

1. **Hito 4/14:** construir fixtures de operaciones CAD avanzadas por motor y ejecutar las recipes de loft, sweep, vaciado, transición, relieve y OCP permitido. Su existencia como orientación de API no certifica robustez de todas las combinaciones.
2. **Hito 14:** realizar una prueba explícita de Quality Loop completo con proveedores reales, presupuestos pequeños y casos mecánico, orgánico e híbrido; registrar costos, errores y la calidad obtenida. Los tests automáticos usan mocks. En una prueba aislada, Ultra respondió pero su plan no pasó el esquema; Super sí produjo un plan estructuralmente válido. El fallback está probado con mocks, aún no como ejecución completa con ambos servicios.
3. **Hito 14:** ejecutar el conjunto congelado de 60 casos o un conjunto complejo adicional versionado para estimar tasas y comparar condiciones. Hasta entonces no hay evidencia para afirmar una mejora cuantitativa de fidelidad.
4. **Hito 10, opcional:** evaluar Cosmos solo si el ID aparece en el catálogo y se valida su capacidad visual; permanece desactivado.
5. **Hito 5/14, integraciones opcionales:** GLM 5.3 entregó contenido vacío con una solicitud de 64 tokens; probar su salida estructurada con un límite adecuado antes de elegirlo como juez. En la verificación del 2026-10-06, DeepSeek V4.1 Flash servido por NVIDIA agotó 110 segundos y Laguna XS devolvió HTTP 503. Nemotron Super, Ultra y Kimi K3 sí entregaron código Python sintácticamente válido; por eso son los generadores visibles con clave NVIDIA y Super es el predeterminado. Una ejecución real `open-loop` con Super y CadQuery produjo STEP/STL válidos para una placa sencilla. Véase la tabla y los límites de estas pruebas en `README_APLICACION.md`. Aún falta validar Quality Loop completo y fidelidad geométrica en los 60 casos.
