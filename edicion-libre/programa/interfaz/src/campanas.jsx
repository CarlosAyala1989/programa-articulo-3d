import React, { useEffect, useState } from 'react';
import './estudio.css';
import ComparativaExterna from './comparativa.jsx';

const motoresBase = ['cadquery', 'build123d', 'freecad'];
const modosBase = ['open-loop', 'closed-loop'];

async function pedir(url, opciones) {
  const respuesta = await fetch(url, opciones);
  const datos = await respuesta.json();
  if (!respuesta.ok) throw new Error(typeof datos.detail === 'string' ? datos.detail : 'No se pudo completar la operación.');
  return datos;
}

function Alternador({ titulo, valores, seleccionados, cambiar, etiquetas, deshabilitado = false }) {
  return <fieldset className="alternador"><legend>{titulo}</legend>{valores.map((valor) => <label key={valor} className="opcion-check"><input type="checkbox" disabled={deshabilitado} checked={seleccionados.includes(valor)} onChange={() => cambiar(seleccionados.includes(valor) ? seleccionados.filter((dato) => dato !== valor) : [...seleccionados, valor])} />{etiquetas?.[valor] || valor}</label>)}</fieldset>;
}

function BarraIteraciones({ fila, tipo }) {
  if (!fila.n_evaluable) return <span className="sin-denominador">Sin datos evaluables</span>;
  const valores = tipo === 'codigo' ? fila.primer_exito_ejecucion : fila.primer_exito_cad_exportable;
  const colores = ['#72d4c4', '#4aa9d2', '#8689da', '#c39ce3', '#efb770'];
  return <div className="grafico-iteraciones" aria-label={`Éxitos por intento de ${fila.modelo} ${fila.motor} ${fila.nivel}`}>
    {valores.map((cantidad, indice) => <div key={indice} className="segmento-iteracion" style={{ width: `${100 * cantidad / fila.n_evaluable}%`, background: colores[indice] }} title={`Intento ${indice + 1}: ${cantidad}`} />)}
    <div className="segmento-fallo" style={{ width: `${100 * (fila.n_evaluable - valores.reduce((a, b) => a + b, 0)) / fila.n_evaluable}%` }} title={`Sin éxito: ${fila.n_evaluable - valores.reduce((a, b) => a + b, 0)}`} />
  </div>;
}



function ImportadorPrompts45({ alImportar }) {
  const [archivo, cambiarArchivo] = useState(null);
  const [nombre, cambiarNombre] = useState('CAD-LLMIA-45');
  const [version, cambiarVersion] = useState('1.0.0');
  const [ocupado, cambiarOcupado] = useState(false);
  const [error, cambiarError] = useState('');
  async function importar(evento) {
    evento.preventDefault(); cambiarError(''); cambiarOcupado(true);
    try {
      const texto = await archivo.text();
      const cuerpo = archivo.name.toLowerCase().endsWith('.json')
        ? { documento: { ...JSON.parse(texto.replace(/^\uFEFF/, '')), nombre, version } }
        : { csv: texto, nombre, version };
      const datos = await pedir('/api/lote-45/importar', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo) });
      await alImportar(datos.identificador); cambiarArchivo(null);
    } catch (fallo) { cambiarError(fallo.message); }
    finally { cambiarOcupado(false); }
  }
  return <details className="referencia-panel"><summary><strong>Importar mis 45 prompts</strong></summary><form onSubmit={importar}>
    <p>CSV o JSON con código, nivel (basico/intermedio/complejo), familia, fundamento y descripción. Se valida y congela una versión independiente.</p>
    <a href="/api/lote-45/plantilla.csv">Descargar plantilla CSV de 45 filas ↓</a>
    <div className="campos"><div><label htmlFor="nombre-lote">NOMBRE DEL CONJUNTO</label><input id="nombre-lote" maxLength={120} required value={nombre} onChange={(e) => cambiarNombre(e.target.value)} /></div><div><label htmlFor="version-lote">VERSIÓN</label><input id="version-lote" maxLength={30} required value={version} onChange={(e) => cambiarVersion(e.target.value)} /></div><div><label htmlFor="archivo-lote">ARCHIVO DE PROMPTS</label><input id="archivo-lote" type="file" accept=".csv,.json" onChange={(e) => cambiarArchivo(e.target.files?.[0] || null)} /></div></div>
    <button type="submit" disabled={!archivo || ocupado}>{ocupado ? 'Importando…' : 'Importar y congelar los 45 prompts'}</button>{error && <p className="error" role="alert">{error}</p>}
  </form></details>;
}

function ReferenciaPanel({ conjunto, alActualizar }) {
  const [codigo, cambiarCodigo] = useState('');
  const [archivo, cambiarArchivo] = useState(null);
  const [procedencia, cambiarProcedencia] = useState('');
  const [mensaje, cambiarMensaje] = useState('');
  const caso = conjunto.casos.find((dato) => dato.codigo === codigo);
  async function cargar(evento) {
    evento.preventDefault();
    if (!caso || !archivo) return;
    try {
      const respuesta = await fetch(`/api/casos/${caso.identificador}/referencia?procedencia=${encodeURIComponent(procedencia)}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/octet-stream' }, body: archivo,
      });
      const datos = await respuesta.json();
      if (!respuesta.ok) throw new Error(datos.detail || 'Referencia no aceptada');
      cambiarMensaje(`Referencia validada · volumen ${datos.volumen_mm3.toFixed(2)} mm³`);
      cambiarArchivo(null); cambiarProcedencia(''); alActualizar();
    } catch (fallo) { cambiarMensaje(fallo.message); }
  }
  return <form className="referencia-panel" onSubmit={cargar}><h3>Referencia CAD independiente</h3><p>Opcional. Se usa para IoU y Chamfer digital; no se envía al modelo de IA.</p><div className="campos"><div><label htmlFor="caso-referencia">CASO</label><select id="caso-referencia" value={codigo} onChange={(evento) => cambiarCodigo(evento.target.value)}><option value="">Seleccionar</option>{conjunto.casos.map((dato) => <option key={dato.codigo} value={dato.codigo}>{dato.codigo} · {dato.nivel}{dato.referencia_sha256 ? ' · con referencia' : ''}</option>)}</select></div><div><label htmlFor="archivo-referencia">STEP INDEPENDIENTE</label><input id="archivo-referencia" type="file" accept=".step,.stp" onChange={(evento) => cambiarArchivo(evento.target.files?.[0] || null)} /></div><div><label htmlFor="procedencia-referencia">PROCEDENCIA / AUTOR</label><input id="procedencia-referencia" value={procedencia} onChange={(evento) => cambiarProcedencia(evento.target.value)} placeholder="Origen y validación del CAD" /></div></div><button type="submit" disabled={!caso || caso.referencia_sha256 || !archivo || procedencia.trim().length < 8}>Adjuntar y validar STEP</button>{caso?.referencia_sha256 && <small>Este caso ya tiene referencia inmutable: {caso.referencia_sha256.slice(0, 16)}…</small>}{mensaje && <small>{mensaje}</small>}</form>;
}

export default function PanelInvestigacion({ pagina, opciones, alElegirCaso }) {
  const [conjuntos, cambiarConjuntos] = useState([]);
  const [conjunto, cambiarConjunto] = useState(null);
  const [campanas, cambiarCampanas] = useState([]);
  const [campanaActual, cambiarCampanaActual] = useState('');
  const [resumen, cambiarResumen] = useState(null);
  const [metricas, cambiarMetricas] = useState(null);
  const [nombre, cambiarNombre] = useState('Mi campaña CAD');
  const [tipo, cambiarTipo] = useState('seleccion');
  const [usarReferencias, cambiarUsarReferencias] = useState(false);
  const [nivelFigura, cambiarNivelFigura] = useState('todos');
  const [casosElegidos, cambiarCasosElegidos] = useState([]);
  const [modelos, cambiarModelos] = useState([]);
  const [motores, cambiarMotores] = useState([]);
  const [modos, cambiarModos] = useState([]);
  const [semilla, cambiarSemilla] = useState(20261004);
  const [repeticiones, cambiarRepeticiones] = useState(1);
  const [vista, cambiarVista] = useState(null);
  const [error, cambiarError] = useState('');
  const [avisoExportacion, cambiarAvisoExportacion] = useState('');
  const [ocupado, cambiarOcupado] = useState(false);
  const [tipoGrafico, cambiarTipoGrafico] = useState('codigo');

  async function recargar(preferido = null) {
    try {
      const [nuevosConjuntos, nuevasCampanas] = await Promise.all([pedir('/api/conjuntos'), pedir('/api/campanas')]);
      cambiarConjuntos(nuevosConjuntos);
      cambiarCampanas(nuevasCampanas);
      const principal = nuevosConjuntos.find((dato) => dato.identificador === (preferido || conjunto?.identificador)) || [...nuevosConjuntos].reverse().find((dato) => dato.finalidad === 'evaluacion_local_45') || nuevosConjuntos.find((dato) => dato.nombre === 'CAD-LLMIA-60') || nuevosConjuntos[0];
      if (principal) cambiarConjunto(await pedir(`/api/conjuntos/${principal.identificador}`));
    } catch (fallo) { cambiarError(fallo.message); }
  }

  useEffect(() => { recargar(); }, []);
  useEffect(() => {
    if (campanaActual || pagina !== 'campanas') return undefined;
    const intervalo = setInterval(() => recargar(), 5000);
    return () => clearInterval(intervalo);
  }, [campanaActual, pagina, conjunto?.identificador]);
  useEffect(() => { cambiarVista(null); }, [nombre, tipo, conjunto?.identificador, casosElegidos, modelos, motores, modos, semilla, repeticiones, usarReferencias]);
  useEffect(() => {
    if (!campanaActual || !['campanas', 'metricas'].includes(pagina)) return undefined;
    cambiarResumen(null); cambiarMetricas(null); cambiarAvisoExportacion('');
    let activo = true;
    async function actualizar() {
      try {
        const nuevoResumen = await pedir(`/api/campanas/${campanaActual}`);
        if (!activo) return;
        cambiarResumen(nuevoResumen);
        cambiarCampanas((anteriores) => anteriores.map((campana) => campana.identificador === nuevoResumen.identificador ? nuevoResumen : campana));
        // Un fallo de métricas no debe congelar el enlace a la ejecución activa.
        const nuevasMetricas = await pedir(`/api/campanas/${campanaActual}/metricas`);
        if (activo) cambiarMetricas(nuevasMetricas);
      } catch (fallo) { if (activo) cambiarError(fallo.message); }
      finally { if (activo) temporizador = setTimeout(actualizar, 4000); }
    }
    let temporizador;
    actualizar();
    return () => { activo = false; clearTimeout(temporizador); };
  }, [campanaActual, pagina]);


  async function elegirConjunto(identificador) {
    try { cambiarConjunto(await pedir(`/api/conjuntos/${identificador}`)); cambiarVista(null); cambiarUsarReferencias(false); cambiarCasosElegidos([]); }
    catch (fallo) { cambiarError(fallo.message); }
  }

  function elegirTipo(nuevoTipo) {
    cambiarTipo(nuevoTipo); cambiarVista(null);
    if (nuevoTipo === 'lote-45') { cambiarModelos(['L01', 'L02', 'L03', 'L04', 'L05']); cambiarMotores(motoresBase); cambiarModos(modosBase); cambiarRepeticiones(1); }
  }

  const solicitud = () => ({
    nombre, conjunto_identificador: conjunto?.identificador, modelos, motores, modos,
    esfuerzo_razonamiento: null,
    repeticiones: Number(repeticiones), semilla: Number(semilla), tipo,
    codigos_caso: ['piloto', 'seleccion'].includes(tipo) ? casosElegidos : null,
    usar_referencias: usarReferencias,
    presupuesto_usd: null,
  });

  async function ejecutarAccion(ruta, cuerpo, alTerminar) {
    cambiarError(''); cambiarOcupado(true);
    try {
      const datos = await pedir(ruta, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo) });
      alTerminar(datos);
    } catch (fallo) { cambiarError(fallo.message); }
    finally { cambiarOcupado(false); }
  }

  async function controlar(accion) {
    if (!campanaActual) return;
    await ejecutarAccion(`/api/campanas/${campanaActual}/${accion}`, {}, (datos) => {
      cambiarResumen(datos); recargar();
    });
  }

  const conteos = conjunto?.por_nivel || {};
  const filas = metricas?.filas || [];
  const estados = resumen?.estados_ejecucion || {};
  const completadas = (estados.completada || 0) + (estados.fallida || 0);

  if (!['casos', 'campanas', 'metricas'].includes(pagina)) return null;

  return <section className="investigacion">
    {pagina === 'campanas' && <p className="nota-campana"><strong>Inicio manual:</strong> elige el conjunto de prompts, los modelos instalados y las librerías CAD. Calcula la matriz, guarda la campaña y pulsa «Iniciar campaña» cuando estés listo. Abrir el programa conserva las campañas pausadas. Descarga los resultados desde la campaña.</p>}
    {['casos', 'campanas'].includes(pagina) && <details className="panel-campana" open={pagina === 'casos'}><summary><strong>Conjuntos de prompts e importación</strong></summary><label htmlFor="conjunto-activo">CONJUNTO DE PROMPTS</label><select id="conjunto-activo" value={conjunto?.identificador || ''} onChange={(e) => elegirConjunto(e.target.value)}>{conjuntos.map((dato) => <option key={dato.identificador} value={dato.identificador}>{dato.nombre} · {dato.version} · {dato.total} prompts</option>)}</select><ImportadorPrompts45 alImportar={(id) => recargar(id)} /></details>}

    {pagina === 'casos' && <>
    <div className="titulo-seccion"><span className="numero">01</span><div><h2>Conjunto de evaluación</h2><p>Prompts por dificultad, conjuntos originales e importados.</p></div></div>
    {conjunto && <>
      <div className="resumen-dataset"><div><small>VERSIÓN</small><strong>{conjunto.nombre} · {conjunto.version}</strong></div><div><small>CASOS</small><strong>{conjunto.total}</strong></div><div><small>BÁSICO / INTERMEDIO / COMPLEJO</small><strong>{conteos.basico} / {conteos.intermedio} / {conteos.complejo}</strong></div><div><small>HUELLA SHA-256</small><code>{conjunto.huella_sha256?.slice(0, 16)}…</code></div></div>
      <div className="enlaces"><a href={`/api/conjuntos/${conjunto.identificador}/exportar.json`}>Descargar los {conjunto.total} prompts JSON ↓</a></div>
      <ReferenciaPanel conjunto={conjunto} alActualizar={recargar} />
      <div className="lista-casos">{['basico', 'intermedio', 'complejo'].map((nivel) => <details key={nivel}><summary>{nivel.toUpperCase()} · {conteos[nivel] || 0} casos</summary><div className="casos-interior">{conjunto.casos.filter((caso) => caso.nivel === nivel).map((caso) => <article key={caso.codigo} className="caso"><div><strong>{caso.codigo}</strong><span>{caso.familia.replaceAll('_', ' ')}</span></div><p>{caso.descripcion}</p><small>{caso.fundamento}</small><button type="button" onClick={() => { alElegirCaso(caso);  }}>Usar en generación individual</button></article>)}</div></details>)}</div>
    </>}

    </>}
    {error && <p className="error" role="alert">{error}</p>}
    {pagina === 'campanas' && <>
    <details className="panel-campana" open><summary><strong>Preparar una campaña</strong></summary>
    <div className="titulo-seccion"><span className="numero">01</span><div><h2>Campaña de generación</h2><p>Prepara una nueva matriz independiente.</p></div></div>
    <div><div className="campos"><div><label htmlFor="nombre-campana">NOMBRE</label><input id="nombre-campana" value={nombre} onChange={(evento) => cambiarNombre(evento.target.value)} /></div><div><label htmlFor="tipo-campana">TIPO</label><select id="tipo-campana" value={tipo} onChange={(evento) => elegirTipo(evento.target.value)}><option value="seleccion">Selección manual de prompts, modelos y librerías</option><option value="lote-45">Estudio aprobado · 45 prompts · 5 modelos</option><option value="piloto">Piloto parcial</option><option value="principal">Histórico · 60 casos</option></select></div></div>
      {tipo === 'lote-45' && <p className="nota-campana">45 × 2 estrategias × 3 motores × 5 modelos = <strong>1.350 ejecuciones</strong>, hasta 4.050 intentos del benchmark. Las recuperaciones operativas pueden repetir llamadas cuya respuesta se perdió. Se procesan una por una: 45 Open-loop y 45 Closed-loop por motor y modelo. El estudio utiliza los 45 prompts aprobados por la dirección de la investigación. El conjunto histórico de 60 se conserva por separado.</p>}
      {tipo === 'lote-45' && conjunto?.finalidad !== 'evaluacion_local_45' && <p className="error">Importa o selecciona el conjunto de 45 prompts para este lote.</p>}
      <label className="opcion-check"><input type="checkbox" checked={usarReferencias} onChange={(e) => cambiarUsarReferencias(e.target.checked)} />Calcular IoU con los STEP independientes adjuntos. Solo evaluación; nunca se envían al modelo.</label>
      <p>Los modelos se detectan al abrir la aplicación. Si acabas de instalar otro, vuelve a abrirla para actualizar la lista.</p>{opciones && !Object.keys(opciones.modelos || {}).length && <p className="error">No hay modelos disponibles. Abre Ollama y vuelve a abrir la aplicación.</p>}<div className="matriz-opciones"><Alternador titulo="Modelos IA" valores={Object.keys(opciones?.modelos || {})} seleccionados={modelos} cambiar={cambiarModelos} etiquetas={opciones?.modelos} deshabilitado={tipo === 'lote-45'} /><Alternador titulo="Librerías / motores CAD" valores={motoresBase} seleccionados={motores} cambiar={cambiarMotores} etiquetas={opciones?.motores} deshabilitado={tipo === 'lote-45'} /><Alternador titulo="Estrategias" valores={modosBase} seleccionados={modos} cambiar={cambiarModos} etiquetas={opciones?.modos} deshabilitado={tipo === 'lote-45'} /></div>
      {['piloto', 'seleccion'].includes(tipo) && <div className="seleccion-casos"><label>PROMPTS · {casosElegidos.filter((codigo) => conjunto?.casos.some((caso) => caso.codigo === codigo)).length} SELECCIONADOS</label><div className="acciones"><button type="button" onClick={() => cambiarCasosElegidos(conjunto?.casos.map((caso) => caso.codigo) || [])}>Seleccionar los {conjunto?.total || 0} prompts</button><button type="button" onClick={() => cambiarCasosElegidos([])}>Quitar selección</button></div><div>{conjunto?.casos.map((caso) => <label key={caso.codigo} className="opcion-check"><input type="checkbox" checked={casosElegidos.includes(caso.codigo)} onChange={() => cambiarCasosElegidos(casosElegidos.includes(caso.codigo) ? casosElegidos.filter((codigo) => codigo !== caso.codigo) : [...casosElegidos, caso.codigo])} />{caso.codigo}</label>)}</div></div>}
      <div className="campos"><div><label htmlFor="repeticiones">REPETICIONES</label><input type="number" id="repeticiones" disabled={tipo === 'lote-45'} min="1" max="5" value={repeticiones} onChange={(evento) => cambiarRepeticiones(evento.target.value)} /></div><div><label htmlFor="semilla">SEMILLA</label><input type="number" id="semilla" value={semilla} onChange={(evento) => cambiarSemilla(evento.target.value)} /></div></div>
      <div className="acciones"><button type="button" disabled={ocupado || !conjunto || !modelos.length || !motores.length || !modos.length || (['seleccion', 'piloto'].includes(tipo) && !casosElegidos.length) || (tipo === 'lote-45' && conjunto.finalidad !== 'evaluacion_local_45')} onClick={() => ejecutarAccion('/api/campanas/previsualizar', solicitud(), cambiarVista)}>Calcular matriz</button><button type="button" disabled={ocupado || !vista} onClick={() => ejecutarAccion('/api/campanas', solicitud(), (datos) => { cambiarCampanaActual(datos.identificador); cambiarVista(null); recargar(); })}>Guardar campaña</button></div>
      {vista && <div className="vista-previa"><strong>{vista.ejecuciones} ejecuciones · hasta {vista.maximo_generaciones} generaciones</strong><span>{vista.ejecuciones_por_modelo} ejecuciones por modelo · cola secuencial · sin cargo de API</span><small>La duración depende del hardware y del modelo. No se estima el coste de electricidad.</small></div>}
    </div></details>

    </>}
    {pagina !== 'casos' && <>
    <div className="titulo-seccion"><span className="numero">{pagina === 'campanas' ? '02' : '01'}</span><div><h2>{pagina === 'campanas' ? 'Seguimiento de campaña' : 'Resultados digitales'}</h2><p>{pagina === 'campanas' ? 'Selecciona una campaña guardada para iniciarla o seguir su progreso.' : 'Métricas con denominadores y exportaciones.'}</p></div></div>
    <div className="panel-resultados"><label htmlFor="campana-elegida">CAMPAÑA</label><select id="campana-elegida" value={campanaActual} onChange={(evento) => cambiarCampanaActual(evento.target.value)}><option value="">Selecciona una campaña</option>{campanas.map((dato) => <option key={dato.identificador} value={dato.identificador}>{dato.nombre} · {dato.estado}</option>)}</select>
      {resumen && <><div className="resumen-dataset"><div><small>ESTADO</small><strong>{resumen.estado}</strong></div><div><small>PROGRESO CIENTÍFICO</small><strong>{completadas} / {resumen.total_ejecuciones}</strong></div><div><small>BLOQUEADAS</small><strong>{estados.bloqueada || 0}</strong></div><div><small>INFERENCIA LOCAL</small><strong>Sin tarifa por API</strong></div></div><p className="nota-campana">{resumen.mensaje}</p>{resumen.ejecucion_actual && <p className="nota-campana"><strong>En curso:</strong> {resumen.ejecucion_actual.modelo} · {resumen.ejecucion_actual.motor} · {resumen.ejecucion_actual.modo} · {resumen.ejecucion_actual.caso} · intento {resumen.ejecucion_actual.intento}. <a href={`#/resultado/${resumen.ejecucion_actual.identificador}`}>Ver ejecución →</a></p>}<div className="acciones">{pagina === 'campanas' && ['borrador', 'pausada'].includes(resumen.estado) && <button type="button" disabled={ocupado} onClick={() => controlar('iniciar')}>Iniciar campaña</button>}{pagina === 'campanas' && resumen.estado === 'en_curso' && <button type="button" disabled={ocupado} onClick={() => controlar('pausar')}>Pausar</button>}{pagina === 'campanas' && ['borrador', 'pausada', 'en_curso', 'bloqueada'].includes(resumen.estado) && <button type="button" disabled={ocupado} onClick={() => controlar('cancelar')}>Cancelar pendientes</button>}<button type="button" disabled={ocupado} onClick={() => ejecutarAccion(`/api/campanas/${campanaActual}/actualizar-entregables`, {}, () => cambiarAvisoExportacion('Archivos locales actualizados a partir de los resultados guardados.'))}>Actualizar archivos locales</button></div>{avisoExportacion && <p className="nota-campana" role="status">{avisoExportacion}</p>}<div className="enlaces">{pagina === 'campanas' && <a href="#/metricas">Ver métricas →</a>}<a href={`/api/campanas/${campanaActual}/metricas.csv`}>Métricas CSV ↓</a><a href={`/api/campanas/${campanaActual}/datos.json`}>Datos y trazas JSON ↓</a><a href={`/api/campanas/${campanaActual}/manufacturabilidad.csv`}>Manufacturabilidad CSV ↓</a><a href={`/api/campanas/${campanaActual}/entregables-fisicos.zip`}>Metrología, fotos y mapas ZIP ↓</a><a href={`/api/campanas/${campanaActual}/tabla-digital.csv`}>Tabla Digital Metrics CSV ↓</a><a href={`/api/campanas/${campanaActual}/entregables.zip`}>Todos los entregables ZIP ↓</a></div></>}
      {pagina === 'campanas' && resumen?.estado === 'bloqueada' && <div className="acciones"><button type="button" disabled={ocupado} onClick={() => controlar('iniciar')}>Continuar ejecuciones pendientes</button><small>Las ejecuciones bloqueadas conservan su estado y quedan fuera de las tasas finales.</small></div>}
      {pagina === 'metricas' && metricas && <><ComparativaExterna key={campanaActual} campana={campanaActual} alImportar={async () => cambiarMetricas(await pedir(`/api/campanas/${campanaActual}/metricas`))} /><div className="referencia-panel"><h3>Figura · Compile Rate por iteración</h3><label htmlFor="nivel-figura">DIFICULTAD</label><select id="nivel-figura" value={nivelFigura} onChange={(e) => cambiarNivelFigura(e.target.value)}><option value="todos">Todos los prompts</option><option value="basico">Básico</option><option value="intermedio">Intermedio</option><option value="complejo">Complejo</option></select><div className="enlaces"><a href={`/api/campanas/${campanaActual}/figura.svg?nivel=${nivelFigura}`}>Figura SVG ↓</a><a href={`/api/campanas/${campanaActual}/figura.png?nivel=${nivelFigura}`}>Figura PNG ↓</a></div><p>La tabla Digital Metrics incluye IR de código, IR de CAD e IoU con denominadores. Las filas de literatura llevan fuente y se marcan como contexto: sus datasets y dificultades no son equivalentes a este lote.</p></div><p className="nota-campana">{metricas.final ? 'Cohorte final' : 'Resultados provisionales: hay ejecuciones pendientes o no evaluables.'} Compile Rate indica código que se ejecutó; IR-CAD indica falta de CAD exportable. Las celdas sin denominador aparecen como —.</p><div className="acciones"><button type="button" onClick={() => cambiarTipoGrafico('codigo')} className={tipoGrafico === 'codigo' ? 'activo' : ''}>Éxito de código</button><button type="button" onClick={() => cambiarTipoGrafico('cad')} className={tipoGrafico === 'cad' ? 'activo' : ''}>Éxito CAD</button></div><div className="tabla-contenedor"><table><thead><tr><th>Modelo / motor / nivel / modo</th><th>N evaluable / planificado</th><th>Éxitos por intento</th><th>Compile Rate</th><th>IR código / CAD</th><th>STL watertight</th><th>IoU / Chamfer</th></tr></thead><tbody>{filas.map((fila) => <tr key={`${fila.modelo}-${fila.motor}-${fila.modo}-${fila.nivel}`}><td><strong>{fila.modelo}</strong><br />{fila.motor} · {fila.nivel} · {fila.modo}</td><td>{fila.n_evaluable} / {fila.n_planificado}</td><td><BarraIteraciones fila={fila} tipo={tipoGrafico} /><small>{(tipoGrafico === 'codigo' ? fila.primer_exito_ejecucion : fila.primer_exito_cad_exportable).join(' / ')} · sin éxito {tipoGrafico === 'codigo' ? fila.sin_exito_ejecucion : fila.sin_cad_exportable}</small></td><td>{fila.compile_rate_acumulado_pct.at(-1) ?? '—'} %</td><td>{fila.ir_codigo_pct ?? '—'} / {fila.ir_cad_pct ?? '—'} %</td><td>{fila.topologia.n_watertight} / {fila.topologia.n_stl_analizado}</td><td>{fila.referencias.n_iou ? `${fila.referencias.iou_brep_medio} / ${fila.referencias.chamfer_digital_mm2_medio} mm²` : 'Sin referencia'}</td></tr>)}</tbody></table></div><div className="leyenda">Intentos 1–5: verde, azul, violeta, lila y ámbar · gris: sin éxito. Open-loop conserva únicamente el intento 1.</div></>}
      {pagina === 'metricas' && metricas?.comparaciones_motores?.length > 0 && <div className="tabla-contenedor"><table><thead><tr><th>Comparación pareada frente a CadQuery</th><th>Casos comunes evaluables</th><th>Δ Compile Rate</th><th>Δ éxito CAD</th></tr></thead><tbody>{metricas.comparaciones_motores.map((fila) => <tr key={`${fila.modelo}-${fila.motor_comparado}-${fila.modo}-${fila.nivel}`}><td>{fila.modelo} · {fila.motor_comparado} · {fila.modo} · {fila.nivel}</td><td>{fila.n_pares_evaluables}</td><td>{fila.delta_compile_pct ?? '—'} %</td><td>{fila.delta_exito_cad_pct ?? '—'} %</td></tr>)}</tbody></table></div>}
      {!campanaActual && <p className="nota-campana">{campanas.length ? 'Elige una campaña para consultar su información.' : 'Todavía no hay campañas guardadas.'} {pagina === 'metricas' && <a href="#/campanas">Preparar una campaña →</a>}</p>}
    </div>
    </>}
  </section>;
}
