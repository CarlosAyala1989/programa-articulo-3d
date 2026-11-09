import React, { useEffect, useState } from 'react';
import './biblioteca.css';
import CompararResultado from './metrologia.jsx';

async function consultar(url, opciones) {
  const respuesta = await fetch(url, opciones);
  const datos = await respuesta.json();
  if (!respuesta.ok) throw new Error(typeof datos.detail === 'string' ? datos.detail : 'No se pudo completar la operación.');
  return datos;
}

export function Historial() {
  const [filtros, cambiarFiltros] = useState({ busqueda: '', motor: '', modelo: '', estado: '', campana: '' });
  const [desplazamiento, cambiarDesplazamiento] = useState(0);
  const [datos, cambiarDatos] = useState(null);
  const [error, cambiarError] = useState('');
  const [recarga, cambiarRecarga] = useState(0);
  const [campanas, cambiarCampanas] = useState(null);
  const [errorCampanas, cambiarErrorCampanas] = useState('');
  useEffect(() => {
    let activo = true;
    cambiarErrorCampanas('');
    consultar('/api/campanas')
      .then((valor) => { if (activo) cambiarCampanas(valor); })
      .catch((fallo) => { if (activo) cambiarErrorCampanas(fallo.message); });
    return () => { activo = false; };
  }, [recarga]);
  useEffect(() => {
    let activo = true;
    cambiarDatos(null);
    cambiarError('');
    const temporizador = setTimeout(() => consultar(`/api/ejecuciones?${new URLSearchParams({ ...filtros, desplazamiento })}`)
      .then((valor) => { if (activo) cambiarDatos(valor); })
      .catch((fallo) => { if (activo) cambiarError(fallo.message); }), 250);
    return () => { activo = false; clearTimeout(temporizador); };
  }, [filtros, desplazamiento, recarga]);
  function filtrar(clave, valor) {
    cambiarFiltros(clave === 'campana'
      ? { busqueda: '', motor: '', modelo: '', estado: '', campana: valor }
      : { ...filtros, [clave]: valor });
    cambiarDesplazamiento(0);
  }
  return <section className="tarjeta biblioteca">
    <div className="campana-principal">
      <label htmlFor="campana-historial"><strong>1. Selecciona una campaña</strong></label>
      <select id="campana-historial" value={filtros.campana} disabled={!campanas} onChange={(e) => filtrar('campana', e.target.value)}>
        <option value="">{campanas ? 'Todas las campañas y trabajos individuales' : 'Cargando campañas…'}</option>
        {(campanas || []).map((campana) => <option key={campana.identificador} value={campana.identificador}>{campana.nombre} · {campana.estado} · {campana.identificador.slice(0, 8)}</option>)}
      </select>
      <p>Los filtros de abajo se aplican dentro de la campaña seleccionada. Al cambiar de campaña se limpian esos filtros.</p>
      {campanas?.length === 0 && <p>No hay campañas guardadas. Puedes consultar los trabajos individuales.</p>}
      {errorCampanas && <p className="error" role="alert">No se pudieron cargar las campañas. Pulsa Actualizar historial para reintentar.</p>}
      {filtros.campana && <a href={`/api/campanas/${encodeURIComponent(filtros.campana)}/exportacion-legible`}>Exportar campaña en formato legible</a>}
    </div>
    <fieldset className="filtros-secundarios"><legend>2. Afinar resultados</legend>
    <div className="filtros-biblioteca">
      <label>Buscar prompt o UUID<input value={filtros.busqueda} onChange={(e) => filtrar('busqueda', e.target.value)} /></label>
      <label>Librería<select value={filtros.motor} onChange={(e) => filtrar('motor', e.target.value)}><option value="">Todas</option><option value="cadquery">CadQuery</option><option value="build123d">build123d</option><option value="freecad">FreeCAD</option></select></label>
      <label>Modelo (código)<input value={filtros.modelo} onChange={(e) => filtrar('modelo', e.target.value)} placeholder="Ej. L01" /></label>
      <label>Estado<select value={filtros.estado} onChange={(e) => filtrar('estado', e.target.value)}><option value="">Todos</option>{['completada', 'fallida', 'bloqueada', 'pendiente', 'generando'].map((estado) => <option key={estado}>{estado}</option>)}</select></label>
    </div>
    </fieldset>
    <button type="button" onClick={() => cambiarRecarga(recarga + 1)}>Actualizar historial</button>
    {error && <p role="alert" className="error">{error}</p>}
    {!datos && !error && <p>Consultando trabajos…</p>}
    {datos && <><p>{datos.total} trabajos guardados</p><div className="rejilla-biblioteca">{datos.ejecuciones.map((e) => <article key={e.identificador} className="trabajo-biblioteca">
      <a href={`#/resultado/${e.identificador}`}>{e.miniatura ? <img src={e.miniatura} alt={`Vista de ${e.codigo_prompt}`} loading="lazy" /> : <div className="sin-miniatura">Sin vistas guardadas</div>}<h2>{e.codigo_prompt}{e.origen_identificador ? ' · Variante' : ''}</h2></a>
      <p>{e.descripcion}</p><p>{e.motor} · {e.modelo} · {e.resultado}</p><small>{new Date(e.fecha_creacion).toLocaleString()}</small>{e.estado === 'completada' && <p><a href={`#/resultado/${e.identificador}/comparar`}>Comparar resultado escaneado</a></p>}<p><a href={`/api/ejecuciones/${e.identificador}/exportacion-legible`}>Exportar trabajo</a></p>
    </article>)}</div>{datos.total === 0 && <p>No hay trabajos con estos filtros.</p>}
      <div className="acciones"><button disabled={desplazamiento === 0} onClick={() => cambiarDesplazamiento(Math.max(0, desplazamiento - 24))}>Anterior</button><span>Página {Math.floor(desplazamiento / 24) + 1}</span><button disabled={desplazamiento + 24 >= datos.total} onClick={() => cambiarDesplazamiento(desplazamiento + 24)}>Siguiente</button></div></>}
  </section>;
}

export function AccionesTrabajo({ ejecucion, modelos, alActualizar }) {
  const validos = ejecucion.intentos.filter((i) => i.apto_variante || (i.codigo && i.cad_valido && i.exportacion_valida));
  const [intento, cambiarIntento] = useState(validos.at(-1)?.identificador || '');
  const [modelo, cambiarModelo] = useState(Object.hasOwn(modelos || {}, ejecucion.modelo) ? ejecucion.modelo : '');
  const [modo, cambiarModo] = useState(ejecucion.modo === 'open-loop' ? 'open-loop' : 'closed-loop');
  const [modificacion, cambiarModificacion] = useState('');
  const [ocupado, cambiarOcupado] = useState(false);
  const [error, cambiarError] = useState('');
  async function vistas() {
    cambiarOcupado(true); cambiarError('');
    try { await consultar(`/api/ejecuciones/${ejecucion.identificador}/vistas`, { method: 'POST' }); await alActualizar(); }
    catch (fallo) { cambiarError(fallo.message); }
    finally { cambiarOcupado(false); }
  }
  async function variante(evento) {
    evento.preventDefault(); cambiarOcupado(true); cambiarError('');
    try {
      const datos = await consultar(`/api/ejecuciones/${ejecucion.identificador}/variantes`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ intento_identificador: Number(intento), modificacion, modelo, modo }) });
      window.location.hash = `/resultado/${datos.identificador}`;
    } catch (fallo) { cambiarError(fallo.message); }
    finally { cambiarOcupado(false); }
  }
  return <div className="biblioteca">
    <p><strong>{ejecucion.codigo_prompt} · {ejecucion.resultado}</strong></p>
    <p><a href={`/api/ejecuciones/${ejecucion.identificador}/exportacion-legible`}>Descargar trabajo completo (ZIP)</a></p>
    {ejecucion.campana_identificador && <p><a href={`/api/campanas/${ejecucion.campana_identificador}/exportacion-legible`}>Descargar campaña en formato legible</a></p>}
    {ejecucion.origen_identificador && <p><a href={`#/resultado/${ejecucion.origen_identificador}`}>Trabajo de origen →</a><br />Modificación: {ejecucion.contexto_variante?.modificacion}</p>}
    {ejecucion.variantes?.length > 0 && <details><summary>Variantes creadas ({ejecucion.variantes.length})</summary>{ejecucion.variantes.map((v) => <p key={v.identificador}><a href={`#/resultado/${v.identificador}`}>{v.modificacion}</a></p>)}</details>}
    {ejecucion.archivos.some((a) => a.nombre === 'pieza.stl') && <button type="button" disabled={ocupado} onClick={vistas}>{ocupado ? 'Procesando…' : 'Generar / actualizar vistas'}</button>}
    <div className="rejilla-vistas">{ejecucion.archivos.filter((a) => a.nombre.startsWith('vista-') && !/miniatura|lamina/.test(a.nombre)).map((a) => <a key={a.nombre} href={a.url} download><img src={a.url} alt={a.nombre.replace('vista-', '').replace('.png', '')} /><span>{a.nombre.replace('vista-', '').replace('.png', '')}</span></a>)}</div>
    {ejecucion.estado === 'completada' && ejecucion.archivos.some((a) => a.nombre === 'pieza.stl') && <CompararResultado ejecucion={ejecucion} />}
    <details><summary><strong>Crear variante</strong></summary>{validos.length ? <form onSubmit={variante}>
      <p>Se generará un trabajo nuevo usando el código elegido. Librería: {ejecucion.motor}. Revisa visualmente el resultado para confirmar los cambios.</p>
      <label>Intento de origen<select value={intento} required onChange={(e) => cambiarIntento(e.target.value)}>{validos.map((i) => <option key={i.identificador} value={i.identificador}>Intento {i.numero}</option>)}</select></label>
      <label>Modificación<textarea value={modificacion} required maxLength={4000} rows={4} onChange={(e) => cambiarModificacion(e.target.value)} placeholder="Ej. Añade un agujero de 5 mm en la cara superior" /></label>
      <label>Modelo<select value={modelo} required onChange={(e) => cambiarModelo(e.target.value)}><option value="">Selecciona un modelo disponible</option>{Object.entries(modelos || {}).map(([codigo, nombre]) => <option key={codigo} value={codigo}>{nombre}</option>)}</select></label>
      <label>Estrategia<select value={modo} onChange={(e) => cambiarModo(e.target.value)}><option value="open-loop">Open-loop · un intento</option><option value="closed-loop">Closed-loop · hasta cinco</option></select></label>
      <button className="boton" disabled={ocupado || !modificacion.trim() || !modelo}>Generar variante</button>
    </form> : <p>Este trabajo no conserva un intento con código y CAD exportado válidos para crear una variante.</p>}</details>
    {error && <p role="alert" className="error">{error}</p>}
  </div>;
}
