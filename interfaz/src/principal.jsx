import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import * as THREE from 'three';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { TrackballControls } from 'three/addons/controls/TrackballControls.js';
import { toCreasedNormals } from 'three/addons/utils/BufferGeometryUtils.js';
import PanelInvestigacion from './campanas.jsx';
import CampoEsfuerzo, { nombresEsfuerzo, nivelesEsfuerzo, valorEsfuerzo } from './esfuerzo.jsx';
import LimitesModelo from './limites.jsx';
import { ExportacionesEjecucion } from './exportaciones.jsx';
import './estilos.css';

const nombresMotor = {
  cadquery: 'CadQuery',
  build123d: 'build123d',
  freecad: 'FreeCAD Python API',
};
const nombresModelo = {
  'deepseek-flash': 'DeepSeek Flash',
  'deepseek-v4-pro': 'DeepSeek Pro',
};
const mostrarQualityLoop = false;

function OpcionesModelos({ modelos }) {
  const grupos = [
    ['Otros proveedores', (clave) => !clave.startsWith('codex-cli') && !clave.startsWith('antigravity-cli')],
    ['Codex · suscripción ChatGPT', (clave) => clave.startsWith('codex-cli')],
    ['Antigravity · suscripción Google', (clave) => clave.startsWith('antigravity-cli')],
  ];
  return grupos.map(([nombre, incluir]) => {
    const entradas = Object.entries(modelos || {}).filter(([clave]) => incluir(clave));
    return entradas.length > 0 && <optgroup label={nombre} key={nombre}>{entradas.map(([clave, etiqueta]) => <option value={clave} key={clave}>{etiqueta}</option>)}</optgroup>;
  });
}

function valorMetrica(registro) {
  if (!registro) return 'No disponible';
  if (registro.estado !== 'calculated') return registro.estado.replaceAll('_', ' ');
  const valor = registro.valor;
  if (typeof valor === 'number') return valor.toFixed(4);
  if (typeof valor?.score === 'number') return `${(valor.score * 100).toFixed(1)} %`;
  if (typeof valor?.error_mm === 'number') return `error ${valor.error_mm.toFixed(3)} mm`;
  return 'Calculada';
}

function InformeCalidad({ informe, ejecucionId }) {
  const puntuaciones = informe.quality_metrics?.puntuaciones || {};
  const codigo = informe.code_review || {};
  const visual = informe.visual_review;
  const compuerta = informe.quality_gate || {};
  const tecnico = informe.technical_result || {};
  const critica = informe.critic_review || {};
  const rolesRevisor = { code_reviewer: 'código', visual_reviewer: 'visual', geometric_critic: 'geométrico' };
  const etiquetaEstado = (valor) => valor === true ? 'Sí' : valor === false ? 'No' : 'Sin dato';
  return <details key={informe.candidate_id}>
    <summary><span className={`etiqueta ${informe.quality_success ? 'correcto' : ''}`}>{informe.quality_success ? '✓' : '!'}</span><strong>{informe.candidate_id}</strong><small>{informe.resultado_clasificado === 'reviewer_failed_attempt' ? 'Intento perdido · fallo de revisión' : informe.seleccionado_final ? 'Ganador final' : informe.seleccionado_para_reparacion ? 'Base de reparación' : 'Candidato'}</small></summary>
    <div className="detalle informe-calidad">
      <p><strong>Éxito técnico:</strong> {informe.technical_success ? 'CAD válido y exportable' : 'No se validó técnicamente'} · <strong>Quality Gate:</strong> {compuerta.accepted ? 'aceptado' : 'rechazado'}{typeof compuerta.quality_score === 'number' ? ` · ${(compuerta.quality_score * 100).toFixed(1)} %` : ''}</p>
      <h4>Validación técnica</h4>
      <p>Sintaxis: {etiquetaEstado(tecnico.sintaxis_valida)} · Ejecución: {etiquetaEstado(tecnico.ejecucion_correcta)} · B-Rep: {etiquetaEstado(tecnico.cad_valido)} · Exportación: {etiquetaEstado(tecnico.exportacion_valida)}{typeof tecnico.volumen_mm3 === 'number' && ` · Volumen: ${tecnico.volumen_mm3.toFixed(3)} mm³`}</p>
      {tecnico.diagnostico && <p>Diagnóstico CAD: {tecnico.diagnostico}</p>}
      <h4>Revisión de código</h4>
      <p>{codigo.estado || (codigo.accepted ? 'Aceptado' : 'Rechazado')} {codigo.severity && `· severidad ${codigo.severity}`}</p>
      {codigo.issues?.length > 0 && <ul>{codigo.issues.map((incidencia, indice) => <li key={`${incidencia.categoria}-${indice}`}><strong>{incidencia.categoria}</strong>{incidencia.linea && ` · línea ${incidencia.linea}`} · {incidencia.descripcion}{incidencia.reparacion && ` · Reparación: ${incidencia.reparacion}`}</li>)}</ul>}
      {Object.keys(puntuaciones).length > 0 && <><h4>Métricas</h4><div className="metricas-calidad">{Object.entries(puntuaciones).map(([nombre, registro]) => <div key={nombre}><small>{nombre.replaceAll('_', ' ')}</small><strong>{valorMetrica(registro)}</strong></div>)}</div></>}
      {visual && <><h4>Revisión visual</h4><p>{visual.accepted ? 'Aceptada' : 'Rechazada'} · silueta {(visual.puntuacion_silueta * 100).toFixed(0)} % · proporciones {(visual.puntuacion_proporciones * 100).toFixed(0)} % · features {(visual.puntuacion_features * 100).toFixed(0)} %</p>{visual.observacion && <p>{visual.observacion}</p>}{visual.errores?.length > 0 && <ul>{visual.errores.map((error, indice) => <li key={`${error.feature_id || 'visual'}-${indice}`}>{error.feature_id || 'Pieza'}: {error.causa_probable} · {error.estrategia_reparacion}</li>)}</ul>}</>}
      {informe.lamina?.nombre && <img className="lamina-calidad" src={`/api/ejecuciones/${ejecucionId}/archivos/${informe.lamina.nombre}`} alt={`Ocho vistas CAD del candidato ${informe.candidate_id}`} loading="lazy" />}
      {informe.critic_review && <><h4>Crítica geométrica</h4><p>{critica.accepted ? 'Aceptada' : 'Rechazada'}{critica.observacion && ` · ${critica.observacion}`}</p>{critica.errores?.length > 0 && <ul>{critica.errores.map((error, indice) => <li key={`${error.feature_id || 'geometria'}-${indice}`}>{error.feature_id || 'Pieza'}: {error.causa_probable} · {error.estrategia_reparacion}</li>)}</ul>}</>}
      <h4>Quality Gate</h4>
      <p>{compuerta.accepted ? 'Aceptado' : 'Rechazado'}{typeof compuerta.threshold === 'number' && ` · umbral ${(compuerta.threshold * 100).toFixed(0)} %`}{compuerta.motivo && ` · ${compuerta.motivo}`}</p>
      {informe.provider_error && <p className="error"><strong>Intento perdido:</strong> falló el agente de revisión {rolesRevisor[informe.provider_error.rol] || informe.provider_error.rol} ({informe.provider_error.estado}). {informe.provider_error.error}</p>}
      {compuerta.evidence_missing?.length > 0 && <p>Evidencia faltante: {compuerta.evidence_missing.join(', ')}</p>}
      {compuerta.features_esenciales_incorrectas?.length > 0 && <p>Features esenciales incorrectas: {compuerta.features_esenciales_incorrectas.join(', ')}</p>}
      {compuerta.cotas_explicitas_incorrectas?.length > 0 && <p>Cotas explícitas fuera de tolerancia: {compuerta.cotas_explicitas_incorrectas.join(', ')}</p>}
      <h4>Retroalimentación de reparación</h4>
      {informe.preserved_features?.length > 0 && <p><strong>Preservar en reparación:</strong> {informe.preserved_features.join(', ')}</p>}
      {informe.repair_priority?.length > 0 && <p><strong>Prioridad de reparación:</strong> {informe.repair_priority.join(', ')}</p>}
      {informe.diagnostico && <p>{informe.diagnostico}</p>}
      <small>Protocolo de referencia: {informe.reference_protocol || 'sin referencia'}</small>
    </div>
  </details>;
}

const paginas = {
  generar: ['Generar pieza', 'Describe la geometría y elige cómo construirla.'],
  resultado: ['Resultado 3D', 'Revisa el modelo, los intentos y los archivos de tu ejecución.'],
  casos: ['Prompts CAD', 'Explora los conjuntos de 45 y 60 prompts por dificultad.'],
  campanas: ['Campañas', 'Configura y controla las comparaciones entre modelos y motores CAD.'],
  metricas: ['Métricas', 'Consulta los resultados de una campaña y exporta sus datos.'],
};

function leerRuta() {
  const [pagina, identificador] = window.location.hash.replace(/^#\/?/, '').split('/');
  return { pagina: paginas[pagina] ? pagina : 'generar', identificador: pagina === 'resultado' ? identificador || '' : '' };
}

function navegar(pagina, identificador = '') {
  window.location.hash = `/${pagina}${identificador ? `/${identificador}` : ''}`;
}

function VisorPieza({ url }) {
  const soporte = useRef(null);
  const [problema, cambiarProblema] = useState('');

  useEffect(() => {
    const elemento = soporte.current;
    if (!elemento || !url) return;
    let activo = true;
    const escena = new THREE.Scene();
    const camara = new THREE.PerspectiveCamera(38, 1, 0.1, 10000);
    const renderizador = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderizador.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderizador.outputColorSpace = THREE.SRGBColorSpace;
    elemento.appendChild(renderizador.domElement);
    const controles = new TrackballControls(camara, renderizador.domElement);
    controles.rotateSpeed = 2.5;
    controles.dynamicDampingFactor = 0.12;
    escena.add(new THREE.HemisphereLight(0xffffff, 0x657080, 2.6));
    const luz = new THREE.DirectionalLight(0xffffff, 3);
    luz.position.set(4, 6, 5);
    escena.add(luz);
    const luzRelleno = new THREE.DirectionalLight(0xd8e6ff, 1.4);
    luzRelleno.position.set(-4, -3, -5);
    escena.add(luzRelleno);
    let malla;
    let geometria;
    let material;
    const ajustar = () => {
      const ancho = elemento.clientWidth || 500;
      const alto = elemento.clientHeight || 340;
      camara.aspect = ancho / alto;
      camara.updateProjectionMatrix();
      renderizador.setSize(ancho, alto);
      controles.handleResize();
    };
    const observador = new ResizeObserver(ajustar);
    observador.observe(elemento);
    ajustar();
    new STLLoader().load(
      url,
      (forma) => {
        if (!activo) { forma.dispose(); return; }
        geometria = toCreasedNormals(forma, Math.PI / 6);
        if (geometria !== forma) forma.dispose();
        geometria.computeBoundingBox();
        const caja = geometria.boundingBox;
        const centro = caja.getCenter(new THREE.Vector3());
        geometria.translate(-centro.x, -centro.y, -centro.z);
        material = new THREE.MeshStandardMaterial({ color: '#8eacc9', metalness: 0.15, roughness: 0.42, side: THREE.DoubleSide });
        malla = new THREE.Mesh(geometria, material);
        malla.rotation.x = -Math.PI / 2;
        escena.add(malla);
        // Encajar las ocho esquinas en el campo de visión evita que las
        // esculturas queden diminutas, sin recortar espigas o piezas alargadas.
        const limites = new THREE.Box3().setFromObject(malla);
        const direccion = new THREE.Vector3(1, 0.8, 1).normalize();
        const horizontal = new THREE.Vector3().crossVectors(new THREE.Vector3(0, 1, 0), direccion).normalize();
        const vertical = new THREE.Vector3().crossVectors(direccion, horizontal).normalize();
        const tangenteVertical = Math.tan(THREE.MathUtils.degToRad(camara.fov / 2));
        const tangenteHorizontal = tangenteVertical * camara.aspect;
        let distancia = 10;
        for (const x of [limites.min.x, limites.max.x]) {
          for (const y of [limites.min.y, limites.max.y]) {
            for (const z of [limites.min.z, limites.max.z]) {
              const esquina = new THREE.Vector3(x, y, z);
              const profundidad = esquina.dot(direccion);
              distancia = Math.max(distancia,
                profundidad + Math.abs(esquina.dot(horizontal)) / tangenteHorizontal,
                profundidad + Math.abs(esquina.dot(vertical)) / tangenteVertical);
            }
          }
        }
        distancia *= 1.12;
        camara.position.copy(direccion.multiplyScalar(distancia));
        camara.near = Math.max(distancia / 1000, 0.01);
        camara.far = Math.max(distancia * 20, 1000);
        camara.updateProjectionMatrix();
        camara.lookAt(0, 0, 0);
        controles.update();
      },
      undefined,
      () => { if (activo) cambiarProblema('No se pudo cargar la vista previa STL. El archivo sigue disponible para descargar.'); },
    );
    let cuadro;
    const animar = () => {
      if (!activo) return;
      cuadro = requestAnimationFrame(animar);
      controles.update();
      renderizador.render(escena, camara);
    };
    animar();
    return () => {
      activo = false;
      cancelAnimationFrame(cuadro);
      observador.disconnect();
      controles.dispose();
      geometria?.dispose();
      material?.dispose();
      renderizador.dispose();
      elemento.removeChild(renderizador.domElement);
    };
  }, [url]);

  return <div className="visor" ref={soporte}>{problema && <div className="aviso-visor">{problema}</div>}</div>;
}

function RetroalimentacionIntento({ intento }) {
  const datos = intento.solicitud_modelo?.retroalimentacion;
  if (!datos) return null;
  const solicitud = intento.solicitud_modelo.mensajes?.find((mensaje) => mensaje.role === 'user')?.content;
  return <details className="retroalimentacion"><summary><strong>Feedback de corrección</strong></summary><p>La solicitud incluye los errores de los intentos {datos.intentos_fuente.join(', ')} y el programa anterior completo.{datos.repeticiones_error > 1 && ` El error se repitió ${datos.repeticiones_error} veces; se pidió cambiar la estrategia constructiva.`}</p><pre>{solicitud}</pre></details>;
}

function Aplicacion() {
  const [ruta, cambiarRuta] = useState(leerRuta);
  const [tema, cambiarTema] = useState(() => document.documentElement.dataset.tema || 'claro');
  const [descripcion, cambiarDescripcion] = useState('Bloque rectangular de 40 × 25 × 12 mm con un agujero pasante centrado de 8 mm de diámetro.');
  const [motor, cambiarMotor] = useState('cadquery');
  const [modelo, cambiarModelo] = useState('');
  const [esfuerzo, cambiarEsfuerzo] = useState('max');
  const [modo, cambiarModo] = useState('closed-loop');
  const [bestOfN, cambiarBestOfN] = useState(false);
  const [proveedorRevisores, cambiarProveedorRevisores] = useState('nvidia');
  const [casoSeleccionado, cambiarCasoSeleccionado] = useState(null);
  const [opciones, cambiarOpciones] = useState(null);
  const [identificador, cambiarIdentificador] = useState(() => leerRuta().identificador || localStorage.getItem('ciel_ultima_ejecucion') || '');
  const [ejecucion, cambiarEjecucion] = useState(null);
  const [error, cambiarError] = useState('');
  const [problemaResultado, cambiarProblemaResultado] = useState('');
  const [enviando, cambiarEnviando] = useState(false);

  useEffect(() => {
    if (!window.location.hash) window.history.replaceState(null, '', '#/generar');
    const actualizarRuta = () => {
      const nuevaRuta = leerRuta();
      cambiarRuta(nuevaRuta);
      if (nuevaRuta.identificador) cambiarIdentificador(nuevaRuta.identificador);
      window.scrollTo({ top: 0, behavior: 'instant' });
    };
    window.addEventListener('hashchange', actualizarRuta);
    return () => window.removeEventListener('hashchange', actualizarRuta);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.tema = tema;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', tema === 'oscuro' ? '#17181a' : '#f5f5f7');
    try { localStorage.setItem('ciel_tema', tema); } catch { /* La selección sigue funcionando sin almacenamiento. */ }
  }, [tema]);

  useEffect(() => {
    let activo = true;
    let consultando = false;
    async function actualizarOpciones() {
      if (consultando) return;
      consultando = true;
      try {
        const respuesta = await fetch('/api/opciones');
        if (!respuesta.ok) return;
        const datos = await respuesta.json();
        if (activo) cambiarOpciones(datos);
      } catch { /* Conservar las últimas opciones ante un corte temporal. */ }
      finally { consultando = false; }
    }
    actualizarOpciones();
    const temporizador = setInterval(actualizarOpciones, 30000);
    window.addEventListener('focus', actualizarOpciones);
    return () => {
      activo = false;
      clearInterval(temporizador);
      window.removeEventListener('focus', actualizarOpciones);
    };
  }, []);

  useEffect(() => { document.title = `${paginas[ruta.pagina][0]} · Agente Ciel`; }, [ruta.pagina]);

  useEffect(() => {
    if (!identificador) return;
    cambiarEjecucion(null);
    let activo = true;
    let temporizador;
    async function actualizar() {
      try {
        const respuesta = await fetch(`/api/ejecuciones/${identificador}`);
        if (respuesta.status === 404) {
          if (activo) cambiarProblemaResultado('No se encontró esta ejecución. Revisa el enlace o inicia una nueva generación.');
          return;
        }
        if (!respuesta.ok) throw new Error('No se pudo consultar el trabajo.');
        const datos = await respuesta.json();
        if (!activo) return;
        cambiarEjecucion(datos);
        cambiarProblemaResultado('');
        if (['pendiente', 'generando'].includes(datos.estado)) temporizador = setTimeout(actualizar, 1600);
      } catch (fallo) {
        if (activo) {
          cambiarProblemaResultado(fallo.message);
          temporizador = setTimeout(actualizar, 4000);
        }
      }
    }
    actualizar();
    return () => { activo = false; clearTimeout(temporizador); };
  }, [identificador]);

  useEffect(() => {
    const proveedores = opciones?.quality_loop?.proveedores_revisores;
    if (proveedores && !proveedores[proveedorRevisores]) {
      cambiarProveedorRevisores(Object.keys(proveedores)[0] || '');
    }
  }, [opciones, proveedorRevisores]);

  async function iniciar(evento) {
    evento.preventDefault();
    cambiarError('');
    cambiarEnviando(true);
    try {
      const respuesta = await fetch('/api/ejecuciones', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ descripcion, caso_identificador: casoSeleccionado?.identificador || null, motor, modelo, modo,
          best_of_n: modo === 'quality-loop' && bestOfN,
          proveedor_revisores: modo === 'quality-loop' ? proveedorRevisores : 'nvidia',
          esfuerzo_razonamiento: valorEsfuerzo(opciones, modelo, esfuerzo) }),
      });
      const datos = await respuesta.json();
      if (!respuesta.ok) throw new Error(typeof datos.detail === 'string' ? datos.detail : 'No se pudo iniciar la generación.');
      cambiarEjecucion(null);
      cambiarIdentificador(datos.identificador);
      localStorage.setItem('ciel_ultima_ejecucion', datos.identificador);
      navegar('resultado', datos.identificador);
    } catch (fallo) {
      cambiarError(fallo.message);
    } finally {
      cambiarEnviando(false);
    }
  }

  const candidatoSeleccionado = ejecucion?.calidad?.ranking_global?.find((candidato) => candidato.seleccionado_final)?.candidate_id
    || ejecucion?.informes_calidad?.find((informe) => informe.technical_success)?.candidate_id;
  const archivoStl = ejecucion?.archivos?.find((archivo) => archivo.nombre === 'pieza.stl')
    || ejecucion?.archivos?.find((archivo) => candidatoSeleccionado && archivo.nombre === `${candidatoSeleccionado}-pieza.stl`)
    || (ejecucion?.modo === 'quality-loop' && ejecucion?.archivos?.find((archivo) => archivo.nombre.endsWith('-pieza.stl')));
  const activo = ejecucion && ['pendiente', 'generando'].includes(ejecucion.estado);
  const colorEstado = ejecucion?.estado === 'completada' ? 'exito' : ['fallida', 'bloqueada'].includes(ejecucion?.estado) ? 'fallo' : 'proceso';

  return <main className="pagina">
    <header className="cabecera">
      <div className="marca"><span className="marca-icono">C</span><div><strong>AGENTE CIEL</strong><small>GENERACIÓN CAD ASISTIDA</small></div></div>
      <div className="cabecera-derecha"><span className="identidad-estudio"><span className="punto" /> Estudio digital <span className="version">v0.2</span></span><div className="selector-tema" role="group" aria-label="Tema de la interfaz"><button type="button" aria-pressed={tema === 'claro'} onClick={() => cambiarTema('claro')}><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" /></svg>Claro</button><button type="button" aria-pressed={tema === 'oscuro'} onClick={() => cambiarTema('oscuro')}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.5 14A8.5 8.5 0 0 1 10 3.5 8.5 8.5 0 1 0 20.5 14Z" /></svg>Oscuro</button></div></div>
    </header>

    <nav className="navegacion" aria-label="Páginas del estudio">{Object.entries(paginas).map(([clave, [titulo]]) => <a key={clave}
      href={`#/${clave}${clave === 'resultado' && identificador ? `/${identificador}` : ''}`}
      aria-current={ruta.pagina === clave ? 'page' : undefined}>{titulo}</a>)}</nav>
    <section className="encabezado-pagina"><p className="ceja">ESTUDIO CAD DIGITAL</p><h1>{paginas[ruta.pagina][0]}</h1><p>{paginas[ruta.pagina][1]}</p></section>

    {ruta.pagina === 'generar' && <div className="pagina-generacion">
      <section className="tarjeta formulario">
        <div className="titulo-seccion"><span className="numero">01</span><div><h2>Nueva generación</h2><p>Define la pieza y el entorno de construcción.</p></div></div>
        <form onSubmit={iniciar}>
          <label htmlFor="descripcion">DESCRIPCIÓN DE LA PIEZA</label>
          {casoSeleccionado && <p className="nota-campana">Caso {casoSeleccionado.codigo} · {casoSeleccionado.nivel}. <button type="button" className="enlace-boton" onClick={() => cambiarCasoSeleccionado(null)}>Quitar asociación</button></p>}
          <textarea id="descripcion" value={descripcion} onChange={(evento) => { cambiarDescripcion(evento.target.value); cambiarCasoSeleccionado(null); }} minLength={12} rows={7} placeholder="Dimensiones en milímetros, agujeros, radios, posiciones y otras restricciones…" required />
          <div className="contador">{descripcion.length.toLocaleString('es-PE')} caracteres · sin recorte de texto</div>
          <div className="campos"><div><label htmlFor="modelo">MODELO DE IA</label><select id="modelo" value={modelo} onChange={(evento) => { cambiarModelo(evento.target.value); cambiarEsfuerzo(valorEsfuerzo(opciones, evento.target.value)); }} required><option value="">Selecciona un modelo</option><OpcionesModelos modelos={opciones?.modelos || nombresModelo} /></select></div><CampoEsfuerzo identificador="esfuerzo" modelo={modelo} opciones={opciones} valor={esfuerzo} alCambiar={(nivel) => { const destino = opciones?.detalles_esfuerzo?.[modelo]?.modelos_por_esfuerzo?.[nivel]; if (destino) cambiarModelo(destino); cambiarEsfuerzo(nivel); }} /></div>
          <LimitesModelo modelo={modelo} opciones={opciones} />
          <div className="campos"><div><label htmlFor="motor">MOTOR CAD</label><select id="motor" value={motor} onChange={(evento) => cambiarMotor(evento.target.value)}>{Object.entries(opciones?.motores || nombresMotor).map(([clave, nombre]) => <option value={clave} key={clave}>{nombre}</option>)}</select></div><div><label htmlFor="modo">ESTRATEGIA</label><select id="modo" value={modo} onChange={(evento) => cambiarModo(evento.target.value)}><option value="open-loop">Open-loop · una generación</option><option value="closed-loop">Closed-loop · hasta cinco</option>{mostrarQualityLoop && <option value="quality-loop" disabled={!opciones?.quality_loop?.disponible}>Quality Loop · métricas y revisión{!opciones?.quality_loop?.disponible ? ' (revisores no configurados)' : ''}</option>}</select></div></div>
          {modo === 'quality-loop' && <div><label htmlFor="proveedor-revisores">PLANIFICADOR Y REVISORES</label><select id="proveedor-revisores" value={proveedorRevisores} onChange={(evento) => cambiarProveedorRevisores(evento.target.value)} required><option value="" disabled>Selecciona los revisores</option><OpcionesModelos modelos={opciones?.quality_loop?.proveedores_revisores} /></select></div>}
          {opciones?.suscripciones?.configurados?.[modelo] && <p className="nota">Usa la sesión de tu cuenta en segundo plano. Cada generación, reparación y candidato consume la cuota de tu suscripción.</p>}
          {modo === 'quality-loop' && <label className="opcion-best"><input type="checkbox" checked={bestOfN} onChange={(evento) => cambiarBestOfN(evento.target.checked)} /><span><strong>Best-of-N</strong><small>Generar y comparar hasta 3 candidatos por ciclo. Aumenta el uso de modelos; no es comparable directamente con los modos históricos.</small></span></label>}
          <div className="nota">{modo === 'closed-loop' ? <>Hasta <strong>5 generaciones totales</strong>: una inicial y cuatro correcciones si son necesarias.</> : modo === 'quality-loop' ? <>Planner, revisor de código, evaluación CAD y revisión visual; máximo <strong>{opciones?.quality_loop?.maximo_iteraciones || 3} ciclos</strong>, <strong>{opciones?.quality_loop?.maximo_llamadas_ia || 40} llamadas IA</strong> y <strong>{((opciones?.quality_loop?.maximo_tokens_estimados || 800000) / 1000).toFixed(0)} mil tokens presupuestados</strong>. La validez técnica y la aceptación geométrica se reportan por separado.</> : <><strong>Una generación</strong> sin feedback ni corrección.</>} {modo !== 'quality-loop' && 'Se detiene al obtener CAD válido y exportable.'}</div>
          {error && <p className="error" role="alert">{error}</p>}
          <button className="boton" disabled={enviando || !modelo || descripcion.trim().length < 12}>{enviando ? 'Iniciando…' : 'Generar pieza 3D'} <span>↗</span></button>
        </form>
      </section>
      <aside className="guia-generacion"><h2>Tu pieza, paso a paso</h2><ol><li>Describe las dimensiones, curvas y detalles que necesitas.</li><li>Elige un modelo de IA y uno de sus niveles de esfuerzo disponibles.</li><li>Selecciona el motor CAD y la estrategia de generación.</li></ol><p>El resultado se abrirá en su propia página con el visor 360°, los archivos y el diagnóstico de cada intento.</p><a href="#/casos">Explorar los conjuntos de prompts →</a>{identificador && <a href={`#/resultado/${identificador}`}>Ver ejecución →</a>}</aside>
    </div>}

    {ruta.pagina === 'resultado' && <div className="pagina-resultado">
      <section className="tarjeta resultado">
        <div className="titulo-seccion"><span className="numero">02</span><div><h2>Resultado de la ejecución</h2><p>Estado, diagnósticos y entregables.</p></div></div>
        {problemaResultado && <p className="error" role="alert">{problemaResultado}</p>}
        {!ejecucion && <div className="vacio"><div className="vacio-cubo">◇</div><strong>{identificador ? 'Consultando la ejecución' : 'Aún no hay una pieza'}</strong><p>{identificador ? 'El resultado aparecerá aquí cuando la ejecución esté disponible.' : 'Al iniciar una generación verás aquí los intentos, la vista previa y los archivos.'}</p></div>}
        {ejecucion && <>
          <div className={`estado ${colorEstado}`}><span>{ejecucion.estado === 'completada' ? '✓' : ejecucion.estado === 'generando' || ejecucion.estado === 'pendiente' ? '◌' : '!'}</span><div><strong>{ejecucion.modo === 'quality-loop' ? ejecucion.quality_success ? 'CAD aceptado por Quality Gate' : ejecucion.technical_success ? 'CAD técnicamente válido · calidad rechazada' : ejecucion.estado === 'generando' || ejecucion.estado === 'pendiente' ? 'Quality Loop en curso' : 'Quality Loop sin aceptación' : ejecucion.estado === 'completada' ? 'Pieza generada' : ejecucion.estado === 'fallida' ? 'Sin CAD válido' : ejecucion.estado === 'bloqueada' ? 'Ejecución interrumpida' : 'Generando y validando'}</strong><small>{ejecucion.mensaje}</small></div></div>
          <p className="descripcion-resultado">{ejecucion.descripcion}</p>
          <div className="resumen resumen-cuatro"><div><small>MOTOR</small><strong>{nombresMotor[ejecucion.motor]}</strong></div><div><small>MODELO</small><strong>{opciones?.modelos?.[ejecucion.modelo] || nombresModelo[ejecucion.modelo] || ejecucion.modelo}</strong></div><div><small>ESFUERZO</small><strong>{nombresEsfuerzo[ejecucion.esfuerzo_razonamiento] || (nivelesEsfuerzo(opciones, ejecucion.modelo) ? 'Sin registro' : 'No aplica')}</strong></div><div><small>{ejecucion.modo === 'quality-loop' ? 'CANDIDATOS' : 'INTENTOS'}</small><strong>{ejecucion.numero_intentos} / {ejecucion.modo === 'open-loop' ? 1 : ejecucion.modo === 'quality-loop' ? `${(ejecucion.calidad?.maximo_iteraciones || 3) * (ejecucion.calidad?.maximo_candidatos_por_iteracion || 1)}` : 5}</strong></div></div>
          {ejecucion.modo === 'quality-loop' && ejecucion.calidad?.geometric_plan && <div className="historial"><h3>Geometric Plan · {ejecucion.calidad.plan_version}</h3><p className="nota-campana">{ejecucion.calidad.geometric_plan.clase_modelado} · Planner {ejecucion.calidad.planner_model} · {ejecucion.calidad.planner_provider}</p><details><summary>Ver plan geométrico y features</summary><div className="detalle"><p><strong>Clase:</strong> {ejecucion.calidad.geometric_plan.clase_modelado} · <strong>Unidades:</strong> {ejecucion.calidad.geometric_plan.unidades}</p><ul>{ejecucion.calidad.geometric_plan.features.map((feature) => <li key={feature.feature_id}><strong>{feature.feature_id}</strong> · {feature.nombre} ({feature.tipo}){feature.descripcion && ` — ${feature.descripcion}`}</li>)}</ul><p><strong>Operaciones:</strong> {(ejecucion.calidad.geometric_plan.operaciones || []).join(', ') || 'No declaradas'}</p></div></details></div>}
          {ejecucion.modo === 'quality-loop' && <div className="historial"><h3>Resultado de calidad</h3><p className="nota-campana"><strong>CAD técnicamente válido:</strong> {ejecucion.technical_success ? 'Sí' : 'No'} · <strong>Quality Gate aceptado:</strong> {ejecucion.quality_success ? 'Sí' : 'No'} · <strong>Puntuación:</strong> {typeof ejecucion.calidad?.quality_score === 'number' ? `${(ejecucion.calidad.quality_score * 100).toFixed(1)} %` : 'No calculada'} · <strong>Llamadas IA:</strong> {ejecucion.calidad?.llamadas_ia || 0}/{ejecucion.calidad?.maximo_llamadas_ia || 40} · <strong>Tokens presupuestados:</strong> {ejecucion.calidad?.tokens_presupuestados || 0}/{ejecucion.calidad?.maximo_tokens_presupuestados || 800000}</p>{ejecucion.informes_calidad?.map((informe) => <InformeCalidad key={informe.candidate_id} informe={informe} ejecucionId={ejecucion.identificador} />)}{ejecucion.calidad?.ranking_global?.length > 0 && <details><summary>Ranking de candidatos</summary><div className="detalle">{ejecucion.calidad.ranking_global.map((item) => <p key={item.candidate_id}>{item.candidate_id} · ciclo {item.iteracion} · {item.technical_success ? 'CAD válido' : 'CAD no válido'} · {item.quality_success ? 'aceptado' : 'rechazado'} · {typeof item.quality_score === 'number' ? `${(item.quality_score * 100).toFixed(1)} %` : 'sin puntuación'}{item.seleccionado_final ? ' · GANADOR' : ''}</p>)}</div></details>}</div>}
          {activo && <div className="barra"><span /></div>}
          <ExportacionesEjecucion identificador={ejecucion.identificador} provisional={!['completada', 'fallida'].includes(ejecucion.estado)} />
          {archivoStl && <><VisorPieza url={archivoStl.url} /><p className="ayuda-visor">Arrastra para girar 360° en cualquier dirección · rueda para acercar · clic derecho y arrastra para desplazar</p></>}
          {ejecucion.archivos.length > 0 && <div className="entregables"><h3>Archivos de la pieza</h3><div className="lista-archivos">{ejecucion.archivos.map((archivo) => <a key={archivo.nombre} href={archivo.url} download><span>↓</span><strong>{archivo.nombre}</strong><small>{(archivo.tamano_bytes / 1024).toFixed(1)} KB</small></a>)}</div></div>}
          {ejecucion.topologia?.length > 0 && <div className="historial"><h3>Topología de mallas</h3>{ejecucion.topologia.map((informe) => <p key={informe.rol_malla} className="nota-campana">STL {informe.rol_malla}: {informe.estado === 'analizada' ? `${informe.watertight ? 'watertight' : 'abierta'} · DangEL ${informe.dang_el} · ${informe.caras} caras` : informe.diagnostico}</p>)}</div>}
          {ejecucion.comparacion_digital && <p className="nota-campana">Referencia digital: {ejecucion.comparacion_digital.estado === 'calculada' ? `IoU ${ejecucion.comparacion_digital.iou_brep.toFixed(4)} · Chamfer ${ejecucion.comparacion_digital.chamfer_digital_mm2.toFixed(4)} mm²` : ejecucion.comparacion_digital.diagnostico}</p>}
          {ejecucion.intentos.length > 0 && <div className="historial"><h3>Historial de intentos</h3>{ejecucion.intentos.map((intento) => <details key={intento.numero}><summary><span className={`etiqueta ${intento.estado}`}>{intento.estado === 'correcto' ? '✓' : intento.estado === 'consultando_ia' ? '◌' : '!'}</span><strong>Intento {intento.numero}</strong><small>{intento.estado.replaceAll('_', ' ')}</small></summary><div className="detalle"><RetroalimentacionIntento intento={intento} />{intento.modelo_informado && <p><strong>Modelo que respondió:</strong> {intento.modelo_informado}</p>}{intento.solicitud_modelo?.perfil?.fallback_automatico && <p><strong>Respaldo automático:</strong> {intento.solicitud_modelo.perfil.fallback_automatico.modelo_primario} → {intento.solicitud_modelo.perfil.fallback_automatico.modelo_respaldo} · motivo: {intento.solicitud_modelo.perfil.fallback_automatico.causa}</p>}{intento.diagnostico && <p>{intento.diagnostico}</p>}{intento.codigo && <pre>{intento.codigo}</pre>}{intento.tokens_entrada > 0 && <small>{intento.tokens_entrada} tokens de entrada · {intento.tokens_salida} de salida · {intento.duracion_segundos.toFixed(1)} s</small>}</div></details>)}</div>}
        </>}
      </section>
      <div className="acciones acciones-pagina"><a href="#/generar">Nueva generación →</a></div>
    </div>}
    <PanelInvestigacion pagina={ruta.pagina} opciones={opciones} alElegirCaso={(caso) => { cambiarCasoSeleccionado(caso); cambiarDescripcion(caso.descripcion); navegar('generar'); }} />
    <footer>AGENTE CIEL · ESTUDIO DIGITAL · CADQUERY / BUILD123D / FREECAD</footer>
  </main>;
}

createRoot(document.getElementById('raiz')).render(<Aplicacion />);
