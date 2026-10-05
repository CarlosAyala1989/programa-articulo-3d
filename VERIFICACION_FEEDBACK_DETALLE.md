# Verificación de detalle y reparación CAD

Fecha: 4 de octubre de 2026, hora de Lima. Entorno: aplicación Docker local. Esta es una verificación de desarrollo; las ejecuciones siguientes no pertenecen a la campaña científica de 60 casos.

## Problema reproducido

- La ejecución Pro/CadQuery `7a7e7d99-d7d4-484a-a44f-6a4be8810b94` terminó sin CAD válido después de cinco intentos. Los intentos 2–5 devolvieron exactamente el mismo código.
- El sistema anterior sí enviaba feedback, pero el diagnóstico era genérico y recortaba el programa anterior. Al reproducir el intento 2 con el runtime actualizado se localizó el fallo en la línea 91: `pieza = pieza.edges().fillet(1.5)`, aplicado a todas las aristas.
- La cabeza Flash/CadQuery anterior `201f8f55-6188-43f7-9208-057d71b3d60a` era exportable, pero su inspección visual mostró un volumen cilíndrico y rasgos muy simples. Esto separa el problema de validez técnica del de semejanza y detalle.

## Cambios comprobables

1. Cada corrección recibe el objetivo original y el programa anterior completo, sin recortar sus importaciones o final. El límite permitido de programa es de 50.000 caracteres.
2. Recibe todos los fallos anteriores, sus fases, la línea y el fragmento fuente cuando están disponibles, y la traza del último fallo. Las trazas se limitan a 6.000 caracteres; los diagnósticos, a 3.000.
3. Detecta repeticiones del programa mediante AST y repeticiones de la excepción aunque cambien las líneas del código. Pide cambiar la construcción que falla, conservando rasgos y dimensiones.
4. Añade orientación específica sobre fillets globales, perfiles pendientes y duplicados en lofts, ejes de revolución, cortadores sin sólido, APIs inexistentes y relieves desconectados. No sustituye una respuesta fallida por una pieza prefabricada ni descarta sólidos para simular éxito.
5. Guarda el texto efectivo antes de contactar al proveedor, y conserva los diagnósticos del runtime. El historial muestra **Feedback de corrección**. Las ejecuciones pausadas recuperan la evidencia persistida.
6. Flash y Pro usan razonamiento `low`, habilitado, con hasta 16.000 tokens totales de salida. El perfil se registra por intento y condición. Ollama mantiene hasta 8.000 tokens. La versión final es `v4-detalle-feedback-razonamiento`.
7. Refuerza el modelado orgánico, la orientación de los rasgos y la conservación de relieves e incisiones. El brief adicional de cabeza clava Chavín es una interpretación estilizada y respeta lo expresamente solicitado por el usuario.
8. Los tres motores exportan STL nativo con desviación lineal absoluta de 0,02 mm y angular de 0,05 rad. El visor suaviza normales en curvas, manteniendo discontinuidades de 30°. No altera los vértices o los archivos.

## Pruebas automatizadas y de runtime

- 19 pruebas aprobadas: 16 ejecutadas en la imagen de aplicación y las 3 geométricas ejecutadas en la imagen del evaluador. Incluyen cinco fallos simulados, reanudación y captura del cuerpo HTTP que recibe DeepSeek.
- El cuerpo HTTP comprobado contiene el feedback completo, razonamiento habilitado, esfuerzo `low` y límite de 16.000 tokens. Se ejecuta exclusivamente el contenido final devuelto por el proveedor.
- Una esfera de 10 mm de radio se exportó y verificó en los tres runtimes con el perfil fino. CadQuery/build123d: 32.204 triángulos, 1.610.284 bytes. FreeCAD: 32.202 triángulos, 1.610.184 bytes. Los tres conservaron un volumen de 4.188,790204786391 mm³. FreeCAD conservó además un FCStd recuperable.
- La interfaz mostró el feedback acumulado de los intentos 1–4 en el quinto intento del ensayo real, con programa completo y traza. El visor cargó el STL anterior sin errores.

## Ensayos reales durante el ajuste

| Ejecución | Perfil | Resultado |
|---|---|---|
| `1626bda2-46e7-4a7c-8cfb-6594d65064ae` | Primera revisión, razonamiento desactivado | Cinco fallos. Se identificaron perfiles sin registrar y una revolución inválida; la IA cambió el código, pero volvió a usar construcciones incorrectas. |
| `f1e96dc8-e526-45c6-bc5d-bc1314cc5e53` | Orientación adicional de API, razonamiento desactivado | Cinco fallos. Llegó a construir geometría, pero produjo cuatro o cinco sólidos desconectados. |
| `bd2a5dd6-db9a-4f47-a020-7b220b897fbe` | Razonamiento alto, 16.000 tokens | Primer intento agotó la salida antes de emitir código. El segundo entregó código y falló un loft con perfiles duplicados. Se detuvo este ensayo de desarrollo tras conservar ambos resultados. |
| `d6b2b0f2-0ffd-4dc5-8051-ce1438601317` | Perfil final con razonamiento bajo | CAD válido y exportable en el primer intento. STEP de 197.242 bytes y STL nativo de 4.078.384 bytes, con 81.566 triángulos. |

El ensayo final volvió a abrir y verificar los archivos. Las dos mallas son watertight, con DangEL = 0, cero aristas abiertas y cero aristas no manifold. El CAD contiene un sólido válido. El análisis de cada malla informa tres componentes de superficie; no se oculta ese dato ni se confunde con tres sólidos B-Rep. Sin referencia independiente no se calculó semejanza arqueológica.

La vista se inspeccionó en el navegador: el resultado incluye volumen orgánico, espiga, ojos y rasgos faciales. Sigue siendo una interpretación estilizada. El encuadre inicial se ajustó para aprovechar el visor; esto no modifica la geometría. La interfaz final se comprobó en escritorio y a 320 px, sin desbordamiento horizontal o errores de carga del STL, y conservó la rotación. La compilación Vite terminó correctamente y la API fue actualizada en Docker.

## Límites e interpretación

Una malla más fina conserva mejor las curvas que el programa realmente construye; no inventa rasgos ausentes. Un CAD válido y exportable tampoco demuestra parecido visual o fidelidad arqueológica. El closed-loop sigue deteniéndose en el primer CAD válido y exportable, o después de cinco generaciones. No se añadió un evaluador automático de semejanza visual.

Las referencias STEP independientes del protocolo siguen excluidas del prompt. El perfil del STL común del evaluador permanece intacto. Las campañas anteriores conservan sus resultados y deben recrearse antes de ejecutar el nuevo protocolo; no deben mezclarse tasas de plantillas diferentes como una única cohorte.
