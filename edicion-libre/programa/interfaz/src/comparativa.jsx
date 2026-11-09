import React, { useState } from 'react';

export default function ComparativaExterna({ campana, alImportar }) {
  const [archivo, cambiarArchivo] = useState(null);
  const [mensaje, cambiarMensaje] = useState('');
  const [error, cambiarError] = useState('');
  const [ocupado, cambiarOcupado] = useState(false);
  async function importar(evento) {
    evento.preventDefault(); cambiarOcupado(true); cambiarError(''); cambiarMensaje('');
    try {
      const documento = JSON.parse((await archivo.text()).replace(/^\uFEFF/, ''));
      const respuesta = await fetch(`/api/campanas/${campana}/resultados-externos`, { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(documento) });
      const datos = await respuesta.json();
      if (!respuesta.ok) throw new Error(typeof datos.detail === 'string' ? datos.detail : 'Revisa la plantilla: se necesitan resultados booleanos por caso y repetición.');
      cambiarMensaje('Resultados externos registrados. Ya aparecen en la tabla Digital Metrics CSV.');
      await alImportar();
    } catch (e) { cambiarError(e.message); }
    finally { cambiarOcupado(false); }
  }
  return <details className="referencia-panel"><summary><strong>Comparar con resultados de otro método</strong></summary>
    <p>Las cifras bibliográficas incluidas son contexto. Para comparar las mismas dificultades, aporta una ejecución externa de los mismos prompts, con su fuente, condiciones y resultados por caso.</p>
    <div className="enlaces"><a href={`/api/campanas/${campana}/plantilla-resultados-externos.json`}>Descargar plantilla de esta campaña</a></div>
    <p>Completa ejecución correcta y CAD exportable con true o false. La huella del conjunto, casos y repeticiones se validan al importar. Cada archivo queda registrado con su hash.</p>
    <form onSubmit={importar}><label>Resultados externos JSON<input type="file" accept=".json" required onChange={(e) => cambiarArchivo(e.target.files[0] || null)} /></label>
      <button type="submit" disabled={ocupado || !archivo}>{ocupado ? 'Importando…' : 'Importar resultados externos'}</button>
    </form>{mensaje && <p role="status">{mensaje}</p>}{error && <p role="alert" className="error">{error}</p>}
  </details>;
}
