import React from 'react';

export function ExportacionesEjecucion({ identificador, provisional }) {
  const base = `/api/ejecuciones/${identificador}`;
  return <div className="entregables exportaciones">
    <h3>Exportar ejecución</h3>
    <p className="nota-campana">{provisional ? 'Exportación provisional: incluye lo guardado hasta ahora. Descárgala de nuevo cuando termine.' : 'Incluye los intentos, código, trazas y archivos CAD disponibles.'}</p>
    <div className="enlaces"><a href={`${base}/entregables.zip`}>Todo en ZIP ↓</a><a href={`${base}/datos.json`}>Datos y trazas JSON ↓</a><a href={`${base}/intentos.csv`}>Intentos CSV ↓</a></div>
  </div>;
}

export function ExportacionesCampana({ identificador, provisional, tipo, nivel, alCambiarNivel }) {
  const base = `/api/campanas/${identificador}`;
  return <div className="exportaciones">
    <div className="enlaces"><a href={`${base}/metricas.csv`}>Métricas CSV ↓</a><a href={`${base}/datos.json`}>Datos y trazas JSON ↓</a><a href={`${base}/tabla-digital.csv`}>Tabla Digital Metrics CSV ↓</a><a href={`${base}/entregables.zip`}>Todos los entregables ZIP ↓</a></div>
    {provisional && <p className="nota-campana">Exportación provisional: incluye lo guardado hasta ahora. Puedes descargar mientras se genera; vuelve a descargar al terminar.</p>}
    <div className="referencia-panel">
      <h3>Figura · {tipo === 'codigo' ? 'Compile Rate' : 'Éxito CAD exportable'} por iteración</h3>
      <label htmlFor="nivel-figura">DIFICULTAD</label><select id="nivel-figura" value={nivel} onChange={(evento) => alCambiarNivel(evento.target.value)}><option value="todos">Todos los prompts</option><option value="basico">Básico</option><option value="intermedio">Intermedio</option><option value="complejo">Complejo</option></select>
      <div className="enlaces"><a href={`${base}/figura.svg?tipo=${tipo}&nivel=${nivel}`}>Figura SVG ↓</a><a href={`${base}/figura.png?tipo=${tipo}&nivel=${nivel}`}>Figura PNG ↓</a><a href={`${base}/figura.pdf?tipo=${tipo}&nivel=${nivel}`}>Figura PDF ↓</a></div>
      <p>La tabla Digital Metrics incluye IR de código, IR de CAD e IoU con denominadores. Las filas de literatura llevan fuente y se marcan como contexto: sus datasets y dificultades no son equivalentes a este lote.</p>
    </div>
    <details><summary>Más exportaciones</summary><div className="enlaces"><a href={`${base}/registros/ejecuciones.csv`}>Ejecuciones CSV ↓</a><a href={`${base}/registros/intentos.csv`}>Intentos CSV ↓</a><a href={`${base}/registros/geometria.csv`}>Geometría CSV ↓</a></div></details>
  </div>;
}
