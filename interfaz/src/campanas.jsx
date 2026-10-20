import React, { useEffect, useState } from 'react';
import './estudio.css';
import CampoEsfuerzo, { nivelesEsfuerzo, nombresEsfuerzo, valorEsfuerzo } from './esfuerzo.jsx';

const motoresBase = ['cadquery', 'build123d', 'freecad'];
const modosBase = ['open-loop', 'closed-loop'];

async function pedir(url, opciones) {
  const respuesta = await fetch(url, opciones);
  const datos = await respuesta.json();
  if (!respuesta.ok) throw new Error(typeof datos.detail === 'string' ? datos.detail : 'No se pudo completar la operación.');
  return datos;
}

function Alternador({ titulo, valores, seleccionados, cambiar, etiquetas }) {
  return <fieldset className="alternador"><legend>{titulo}</legend>{valores.map((valor) => <label key={valor} className="opcion-check"><input type="checkbox" checked={seleccionados.includes(valor)} onChange={() => cambiar(seleccionados.includes(valor) ? seleccionados.filter((dato) => dato !== valor) : [...seleccionados, valor])} />{etiquetas?.[valor] || valor}</label>)}</fieldset>;
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

function ControlPresupuesto({ campana, alActualizar }) {
  const [valor, cambiarValor] = useState(String(campana.presupuesto_usd || ''));
  const [problema, cambiarProblema] = useState('');
  async function guardar() {
    try {
      const datos = await pedir(`/api/campanas/${campana.identificador}/presupuesto`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ presupuesto_usd: Number(valor) }),
      });
      cambiarProblema(''); alActualizar(datos);
    } catch (fallo) { cambiarProblema(fallo.message); }
  }
  return <div className="control-presupuesto"><label htmlFor="nuevo-tope">TOPE ESTIMADO DE LA CAMPAÑA (USD)</label><input id="nuevo-tope" type="number" min="0.01" step="0.01" value={valor} onChange={(evento) => cambiarValor(evento.target.value)} /><button type="button" onClick={guardar} disabled={!valor || Number(valor) <= 0}>Actualizar tope</button>{problema && <span className="error">{problema}</span>}</div>;
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
  return <form className="referencia-panel" onSubmit={cargar}><h3>Referencia CAD independiente</h3><p>Opcional. Se usa para IoU y Chamfer digital; no se envía al modelo de IA.</p><div className="campos campos-tres"><div><label htmlFor="caso-referencia">CASO</label><select id="caso-referencia" value={codigo} onChange={(evento) => cambiarCodigo(evento.target.value)}><option value="">Seleccionar</option>{conjunto.casos.map((dato) => <option key={dato.codigo} value={dato.codigo}>{dato.codigo} · {dato.nivel}{dato.referencia_sha256 ? ' · con referencia' : ''}</option>)}</select></div><div><label htmlFor="archivo-referencia">STEP INDEPENDIENTE</label><input id="archivo-referencia" type="file" accept=".step,.stp" onChange={(evento) => cambiarArchivo(evento.target.files?.[0] || null)} /></div><div><label htmlFor="procedencia-referencia">PROCEDENCIA / AUTOR</label><input id="procedencia-referencia" value={procedencia} onChange={(evento) => cambiarProcedencia(evento.target.value)} placeholder="Origen y validación del CAD" /></div></div><button type="submit" disabled={!caso || caso.referencia_sha256 || !archivo || procedencia.trim().length < 8}>Adjuntar y validar STEP</button>{caso?.referencia_sha256 && <small>Este caso ya tiene referencia inmutable: {caso.referencia_sha256.slice(0, 16)}…</small>}{mensaje && <small>{mensaje}</small>}</form>;
}

export default function PanelInvestigacion({ pagina, opciones, alElegirCaso }) {
  const [conjuntos, cambiarConjuntos] = useState([]);
  const [conjunto, cambiarConjunto] = useState(null);
  const [campanas, cambiarCampanas] = useState([]);
  const [campanaActual, cambiarCampanaActual] = useState('');
  const [resumen, cambiarResumen] = useState(null);
  const [metricas, cambiarMetricas] = useState(null);
  const [nombre, cambiarNombre] = useState('Piloto digital CAD-LLMIA');
  const [tipo, cambiarTipo] = useState('piloto');
  const [casosElegidos, cambiarCasosElegidos] = useState(['B01', 'I01', 'C01']);
  const [modelos, cambiarModelos] = useState(['deepseek-flash', 'deepseek-v4-pro']);
  const [esfuerzosModelos, cambiarEsfuerzosModelos] = useState({});
  const [motores, cambiarMotores] = useState(motoresBase);
  const [modos, cambiarModos] = useState(modosBase);
  const [semilla, cambiarSemilla] = useState(20261004);
  const [repeticiones, cambiarRepeticiones] = useState(1);
  const [presupuesto, cambiarPresupuesto] = useState('');
  const [vista, cambiarVista] = useState(null);
  const [error, cambiarError] = useState('');
  const [ocupado, cambiarOcupado] = useState(false);
  const [tipoGrafico, cambiarTipoGrafico] = useState('codigo');

  async function recargar() {
    try {
      const [nuevosConjuntos, nuevasCampanas] = await Promise.all([pedir('/api/conjuntos'), pedir('/api/campanas')]);
      cambiarConjuntos(nuevosConjuntos);
      cambiarCampanas(nuevasCampanas);
      const elegido = nuevosConjuntos.find((dato) => dato.identificador === conjunto?.identificador)
        || nuevosConjuntos.find((dato) => dato.nombre === 'CAD-LLMIA-45')
        || nuevosConjuntos.find((dato) => dato.nombre === 'CAD-LLMIA-60') || nuevosConjuntos[0];
      if (elegido) {
        const datos = await pedir(`/api/conjuntos/${elegido.identificador}`);
        cambiarConjunto(datos);
        if (!conjunto) cambiarCasosElegidos(['basico', 'intermedio', 'complejo']
          .map((nivel) => datos.casos.find((caso) => caso.nivel === nivel)?.codigo).filter(Boolean));
      }
    } catch (fallo) { cambiarError(fallo.message); }
  }

  async function elegirConjunto(identificador) {
    cambiarError(''); cambiarConjunto(null); cambiarCasosElegidos([]); cambiarVista(null);
    try {
      const datos = await pedir(`/api/conjuntos/${identificador}`);
      cambiarConjunto(datos);
      if (datos.nombre !== 'CAD-LLMIA-60') cambiarTipo('piloto');
    } catch (fallo) { cambiarError(fallo.message); }
  }

  async function elegirTipo(nuevoTipo) {
    cambiarTipo(nuevoTipo);
    if (nuevoTipo === 'principal' && conjunto?.nombre !== 'CAD-LLMIA-60') {
      const principal = conjuntos.find((dato) => dato.nombre === 'CAD-LLMIA-60');
      if (principal) await elegirConjunto(principal.identificador);
    }
  }

  useEffect(() => { recargar(); }, []);
  useEffect(() => { cambiarVista(null); }, [nombre, tipo, conjunto?.identificador, casosElegidos, modelos, motores, modos, semilla, repeticiones, presupuesto, esfuerzosModelos]);
  useEffect(() => {
    if (!campanaActual || !['campanas', 'metricas'].includes(pagina)) return undefined;
    cambiarResumen(null); cambiarMetricas(null);
    let activo = true;
    async function actualizar() {
      try {
        const [nuevoResumen, nuevasMetricas] = await Promise.all([
          pedir(`/api/campanas/${campanaActual}`), pedir(`/api/campanas/${campanaActual}/metricas`),
        ]);
        if (activo) { cambiarResumen(nuevoResumen); cambiarMetricas(nuevasMetricas); }
      } catch (fallo) { if (activo) cambiarError(fallo.message); }
    }
    actualizar();
    const intervalo = setInterval(actualizar, 4000);
    return () => { activo = false; clearInterval(intervalo); };
  }, [campanaActual, pagina]);

  const solicitud = () => ({
    nombre, conjunto_identificador: conjunto?.identificador, modelos, motores, modos,
    esfuerzos_por_modelo: Object.fromEntries(modelos.filter((modelo) => nivelesEsfuerzo(opciones, modelo))
      .map((modelo) => [modelo, valorEsfuerzo(opciones, modelo, esfuerzosModelos[modelo])])),
    repeticiones: Number(repeticiones), semilla: Number(semilla), tipo,
    codigos_caso: tipo === 'principal' ? null : casosElegidos,
    presupuesto_usd: presupuesto ? Number(presupuesto) : null,
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
  const esfuerzosResumen = resumen?.configuracion?.esfuerzos_por_modelo || Object.fromEntries(
    Object.entries(resumen?.configuracion?.perfiles_generacion || {}).map(([modelo, perfil]) => [modelo, perfil.reasoning_effort]));
  const selectorConjunto = <div className="selector-conjunto"><label htmlFor="conjunto-prompts">CONJUNTO DE PROMPTS</label><select id="conjunto-prompts" value={conjunto?.identificador || ''} onChange={(evento) => elegirConjunto(evento.target.value)} disabled={ocupado || !conjunto || (pagina === 'campanas' && tipo === 'principal')}><option value="" disabled>Cargando conjunto…</option>{conjuntos.map((dato) => <option key={dato.identificador} value={dato.identificador}>{dato.nombre} · {dato.total} prompts · v{dato.version}</option>)}</select>{pagina === 'campanas' && tipo === 'principal' && <p className="nota-campana">La campaña principal usa los 60 casos históricos. Para elegir los 45 prompts, selecciona el tipo Piloto.</p>}</div>;

  if (!['casos', 'campanas', 'metricas'].includes(pagina)) return null;

  return <section className="investigacion">
    {pagina === 'casos' && <>
    <div className="titulo-seccion"><span className="numero">01</span><div><h2>Conjuntos de prompts CAD</h2><p>Selecciona los 45 prompts compartidos con la edición libre o los 60 casos históricos.</p></div></div>
    {selectorConjunto}
    {conjunto && <>
      <div className="resumen-dataset"><div><small>VERSIÓN</small><strong>{conjunto.nombre} · {conjunto.version}</strong></div><div><small>CASOS</small><strong>{conjunto.total}</strong></div><div><small>BÁSICO / INTERMEDIO / COMPLEJO</small><strong>{conteos.basico} / {conteos.intermedio} / {conteos.complejo}</strong></div><div><small>HUELLA SHA-256</small><code>{conjunto.huella_sha256?.slice(0, 16)}…</code></div></div>
      <div className="enlaces"><a href={`/api/conjuntos/${conjunto.identificador}/exportar.json`}>Descargar los {conjunto.total} prompts JSON ↓</a></div>
      <ReferenciaPanel conjunto={conjunto} alActualizar={recargar} />
      <div className="lista-casos">{['basico', 'intermedio', 'complejo'].map((nivel) => <details key={nivel}><summary>{nivel.toUpperCase()} · {conteos[nivel] || 0} casos</summary><div className="casos-interior">{conjunto.casos.filter((caso) => caso.nivel === nivel).map((caso) => <article key={caso.codigo} className="caso"><div><strong>{caso.codigo}</strong><span>{caso.familia.replaceAll('_', ' ')}</span></div><p>{caso.descripcion}</p><small>{caso.fundamento}</small><button type="button" onClick={() => { alElegirCaso(caso);  }}>Usar en generación individual</button></article>)}</div></details>)}</div>
    </>}

    </>}
    {error && <p className="error" role="alert">{error}</p>}
    {pagina === 'campanas' && <>
    <div className="titulo-seccion"><span className="numero">01</span><div><h2>Campaña de generación</h2><p>Prepara la matriz antes de iniciar llamadas de IA.</p></div></div>
    <div className="panel-campana"><div className="campos"><div><label htmlFor="nombre-campana">NOMBRE</label><input id="nombre-campana" value={nombre} onChange={(evento) => cambiarNombre(evento.target.value)} /></div><div><label htmlFor="tipo-campana">TIPO</label><select id="tipo-campana" value={tipo} onChange={(evento) => elegirTipo(evento.target.value)} disabled={!conjunto || ocupado}><option value="piloto">Piloto · selección de prompts</option><option value="principal">Principal · 60 casos</option></select></div></div>
      {selectorConjunto}
      <div className="matriz-opciones"><Alternador titulo="Modelos IA" valores={Object.keys(opciones?.modelos || {})} seleccionados={modelos} cambiar={cambiarModelos} etiquetas={opciones?.modelos} /><Alternador titulo="Motores CAD" valores={motoresBase} seleccionados={motores} cambiar={cambiarMotores} etiquetas={opciones?.motores} /><Alternador titulo="Estrategias" valores={modosBase} seleccionados={modos} cambiar={cambiarModos} etiquetas={opciones?.modos} /></div>
      <div className="campos">{modelos.map((modelo) => <CampoEsfuerzo key={modelo} identificador={`esfuerzo-campana-${modelo}`} etiqueta={`ESFUERZO · ${opciones?.modelos?.[modelo] || modelo}`} modelo={modelo} opciones={opciones} valor={esfuerzosModelos[modelo]} alCambiar={(nivel) => {
        const destino = opciones?.detalles_esfuerzo?.[modelo]?.modelos_por_esfuerzo?.[nivel] || modelo;
        if (destino !== modelo) cambiarModelos([...new Set(modelos.map((actual) => actual === modelo ? destino : actual))]);
        cambiarEsfuerzosModelos((actuales) => ({ ...actuales, [destino]: nivel }));
      }} />)}</div>
      {tipo === 'piloto' && <div className="seleccion-casos"><p className="conteo-seleccion" role="status">PROMPTS DEL PILOTO · {casosElegidos.length} DE {conjunto?.total || 0} SELECCIONADOS</p><div className="acciones acciones-seleccion"><button type="button" disabled={!conjunto || casosElegidos.length === conjunto.total} onClick={() => cambiarCasosElegidos(conjunto.casos.map((caso) => caso.codigo))}>Seleccionar todos los prompts</button><button type="button" disabled={!casosElegidos.length} onClick={() => cambiarCasosElegidos([])}>Quitar selección</button></div><div className="lista-seleccion-casos" role="group" aria-label="Prompts del piloto">{conjunto?.casos.map((caso) => <label key={caso.codigo} className="opcion-check"><input type="checkbox" checked={casosElegidos.includes(caso.codigo)} onChange={() => cambiarCasosElegidos(casosElegidos.includes(caso.codigo) ? casosElegidos.filter((codigo) => codigo !== caso.codigo) : [...casosElegidos, caso.codigo])} />{caso.codigo}</label>)}</div></div>}
      <div className="campos campos-tres"><div><label htmlFor="repeticiones">REPETICIONES</label><input type="number" id="repeticiones" min="1" max="5" value={repeticiones} onChange={(evento) => cambiarRepeticiones(evento.target.value)} /></div><div><label htmlFor="semilla">SEMILLA</label><input type="number" id="semilla" value={semilla} onChange={(evento) => cambiarSemilla(evento.target.value)} /></div><div><label htmlFor="presupuesto">TOPE ESTIMADO USD (OPCIONAL)</label><input type="number" id="presupuesto" min="0.01" step="0.01" value={presupuesto} onChange={(evento) => cambiarPresupuesto(evento.target.value)} placeholder="Sin tope" /></div></div>
      <div className="acciones"><button type="button" disabled={ocupado || !conjunto || !modelos.length || !motores.length || !modos.length || (tipo === 'piloto' && !casosElegidos.length)} onClick={() => ejecutarAccion('/api/campanas/previsualizar', solicitud(), cambiarVista)}>Calcular matriz</button><button type="button" disabled={ocupado || !vista} onClick={() => ejecutarAccion('/api/campanas', solicitud(), (datos) => { cambiarCampanaActual(datos.identificador); cambiarVista(null); recargar(); })}>Guardar campaña</button></div>
      {vista && <div className="vista-previa"><strong>{vista.ejecuciones} ejecuciones · hasta {vista.maximo_generaciones} generaciones</strong><span>Estimación de planificación: USD {vista.costo_planificacion_usd.toFixed(4)}</span><small>{vista.supuesto_costo}. El gasto real depende de tokens y de las tarifas vigentes.</small></div>}
    </div>

    </>}
    {pagina !== 'casos' && <>
    <div className="titulo-seccion"><span className="numero">{pagina === 'campanas' ? '02' : '01'}</span><div><h2>{pagina === 'campanas' ? 'Seguimiento de campaña' : 'Resultados digitales'}</h2><p>{pagina === 'campanas' ? 'Selecciona una campaña guardada para iniciarla o seguir su progreso.' : 'Métricas con denominadores y exportaciones.'}</p></div></div>
    <div className="panel-resultados"><label htmlFor="campana-elegida">CAMPAÑA</label><select id="campana-elegida" value={campanaActual} onChange={(evento) => cambiarCampanaActual(evento.target.value)}><option value="">Selecciona una campaña</option>{campanas.map((dato) => <option key={dato.identificador} value={dato.identificador}>{dato.nombre} · {dato.estado}</option>)}</select>
      {resumen && <><div className="resumen-dataset"><div><small>ESTADO</small><strong>{resumen.estado}</strong></div><div><small>PROGRESO CIENTÍFICO</small><strong>{completadas} / {resumen.total_ejecuciones}</strong></div><div><small>BLOQUEADAS</small><strong>{estados.bloqueada || 0}</strong></div><div><small>GASTO ESTIMADO</small><strong>USD {resumen.gasto_estimado_usd.toFixed(4)}</strong></div></div><p className="nota-campana">{resumen.mensaje}</p><p className="nota-campana">Esfuerzo por modelo: {Object.entries(esfuerzosResumen).filter(([, nivel]) => nivel).map(([modelo, nivel]) => `${opciones?.modelos?.[modelo] || modelo}: ${nombresEsfuerzo[nivel] || nivel}`).join('; ') || 'Sin registro / no aplica'}</p><div className="acciones">{pagina === 'campanas' && ['borrador', 'pausada'].includes(resumen.estado) && <button type="button" disabled={ocupado} onClick={() => controlar('iniciar')}>Iniciar campaña</button>}{pagina === 'campanas' && resumen.estado === 'en_curso' && <button type="button" disabled={ocupado} onClick={() => controlar('pausar')}>Pausar</button>}{pagina === 'campanas' && ['borrador', 'pausada', 'en_curso', 'bloqueada'].includes(resumen.estado) && <button type="button" disabled={ocupado} onClick={() => controlar('cancelar')}>Cancelar pendientes</button>}</div><div className="enlaces">{pagina === 'campanas' && <a href="#/metricas">Ver métricas →</a>}<a href={`/api/campanas/${campanaActual}/metricas.csv`}>Métricas CSV ↓</a><a href={`/api/campanas/${campanaActual}/datos.json`}>Datos y trazas JSON ↓</a></div></>}
      {pagina === 'campanas' && resumen && ['borrador', 'pausada', 'bloqueada'].includes(resumen.estado) && <ControlPresupuesto key={campanaActual} campana={resumen} alActualizar={cambiarResumen} />}
      {pagina === 'campanas' && resumen?.estado === 'bloqueada' && <div className="acciones"><button type="button" disabled={ocupado} onClick={() => controlar('iniciar')}>Continuar ejecuciones pendientes</button><small>Las ejecuciones bloqueadas conservan su estado y quedan fuera de las tasas finales.</small></div>}
      {pagina === 'metricas' && metricas && <><p className="nota-campana">{metricas.final ? 'Cohorte final' : 'Resultados provisionales: hay ejecuciones pendientes o no evaluables.'} Compile Rate indica código que se ejecutó; IR-CAD indica falta de CAD exportable. Las celdas sin denominador aparecen como —.</p><div className="acciones"><button type="button" onClick={() => cambiarTipoGrafico('codigo')} className={tipoGrafico === 'codigo' ? 'activo' : ''}>Éxito de código</button><button type="button" onClick={() => cambiarTipoGrafico('cad')} className={tipoGrafico === 'cad' ? 'activo' : ''}>Éxito CAD</button></div><div className="tabla-contenedor"><table><thead><tr><th>Modelo / motor / nivel / modo</th><th>N evaluable / planificado</th><th>Éxitos por intento</th><th>Compile Rate</th><th>IR-CAD</th><th>STL watertight</th><th>IoU / Chamfer</th></tr></thead><tbody>{filas.map((fila) => <tr key={`${fila.modelo}-${fila.motor}-${fila.modo}-${fila.nivel}`}><td><strong>{fila.modelo}</strong><br />{fila.motor} · {fila.nivel} · {fila.modo}</td><td>{fila.n_evaluable} / {fila.n_planificado}</td><td><BarraIteraciones fila={fila} tipo={tipoGrafico} /><small>{(tipoGrafico === 'codigo' ? fila.primer_exito_ejecucion : fila.primer_exito_cad_exportable).join(' / ')} · sin éxito {tipoGrafico === 'codigo' ? fila.sin_exito_ejecucion : fila.sin_cad_exportable}</small></td><td>{fila.compile_rate_acumulado_pct.at(-1) ?? '—'} %</td><td>{fila.ir_cad_pct ?? '—'} %</td><td>{fila.topologia.n_watertight} / {fila.topologia.n_stl_analizado}</td><td>{fila.referencias.n_iou ? `${fila.referencias.iou_brep_medio} / ${fila.referencias.chamfer_digital_mm2_medio} mm²` : 'Sin referencia'}</td></tr>)}</tbody></table></div><div className="leyenda">Intentos 1–5: verde, azul, violeta, lila y ámbar · gris: sin éxito. Open-loop conserva únicamente el intento 1.</div></>}
      {pagina === 'metricas' && metricas?.comparaciones_motores?.length > 0 && <div className="tabla-contenedor"><table><thead><tr><th>Comparación pareada frente a CadQuery</th><th>Casos comunes evaluables</th><th>Δ Compile Rate</th><th>Δ éxito CAD</th></tr></thead><tbody>{metricas.comparaciones_motores.map((fila) => <tr key={`${fila.modelo}-${fila.motor_comparado}-${fila.modo}-${fila.nivel}`}><td>{fila.modelo} · {fila.motor_comparado} · {fila.modo} · {fila.nivel}</td><td>{fila.n_pares_evaluables}</td><td>{fila.delta_compile_pct ?? '—'} %</td><td>{fila.delta_exito_cad_pct ?? '—'} %</td></tr>)}</tbody></table></div>}
      {!campanaActual && <p className="nota-campana">{campanas.length ? 'Elige una campaña para consultar su información.' : 'Todavía no hay campañas guardadas.'} {pagina === 'metricas' && <a href="#/campanas">Preparar una campaña →</a>}</p>}
    </div>
    </>}
  </section>;
}
