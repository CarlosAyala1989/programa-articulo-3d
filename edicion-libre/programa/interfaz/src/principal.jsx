import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import * as THREE from 'three';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { TrackballControls } from 'three/addons/controls/TrackballControls.js';
import { toCreasedNormals } from 'three/addons/utils/BufferGeometryUtils.js';
import PanelInvestigacion from './campanas.jsx';
import { Historial, AccionesTrabajo } from './biblioteca.jsx';
import './estilos.css';

const nombresMotor = {
  cadquery: 'CadQuery',
  build123d: 'build123d',
  freecad: 'FreeCAD Python API',
};
const nombresModelo = { L01: 'Qwen 3.5 0.8B · Q8_0', L02: 'Qwen 3.5 2B · Q8_0', L03: 'Gemma 3 4B IT', L04: 'Ministral 3 3B · Q6_K', L05: 'SmolLM3 3B · Q6_K' };

function OpcionesModelos({ modelos }) {
  return Object.entries(modelos || {}).map(([clave, nombre]) => <option value={clave} key={clave}>{nombre}</option>);
}

const paginas = {
  historial: ['Historial', 'Abre, exporta y continúa tus trabajos anteriores.'],
  generar: ['Generar pieza', 'Describe la geometría y elige cómo construirla.'],
  resultado: ['Resultado 3D', 'Revisa el modelo, los intentos y los archivos de tu ejecución.'],
  casos: ['Prompts', 'Importa tus 45 prompts o explora los conjuntos y sus referencias digitales.'],
  campanas: ['Campañas', 'Configura y controla las comparaciones entre modelos y motores CAD.'],
  metricas: ['Métricas', 'Consulta los resultados de una campaña y exporta sus datos.'],
};

function leerRuta() {
  const [pagina, identificador] = window.location.hash.replace(/^#\/?/, '').split('/');
  return { pagina: paginas[pagina] ? pagina : 'campanas', identificador: pagina === 'resultado' ? identificador || '' : '' };
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
  const [modo, cambiarModo] = useState('closed-loop');
  const [casoSeleccionado, cambiarCasoSeleccionado] = useState(null);
  const [opciones, cambiarOpciones] = useState(null);
  const [identificador, cambiarIdentificador] = useState(() => leerRuta().identificador || localStorage.getItem('ciel_ultima_ejecucion') || '');
  const [ejecucion, cambiarEjecucion] = useState(null);
  const [error, cambiarError] = useState('');
  const [problemaResultado, cambiarProblemaResultado] = useState('');
  const [enviando, cambiarEnviando] = useState(false);

  useEffect(() => {
    if (!window.location.hash) window.history.replaceState(null, '', '#/campanas');
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
    fetch('/api/opciones').then((respuesta) => respuesta.json()).then(cambiarOpciones).catch(() => {});
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

  async function iniciar(evento) {
    evento.preventDefault();
    cambiarError('');
    cambiarEnviando(true);
    try {
      const respuesta = await fetch('/api/ejecuciones', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ descripcion, caso_identificador: casoSeleccionado?.identificador || null, motor, modelo, modo,
          esfuerzo_razonamiento: null }),
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

  const archivoStl = ejecucion?.archivos?.find((archivo) => archivo.nombre === 'pieza.stl');
  const activo = ejecucion && ['pendiente', 'generando'].includes(ejecucion.estado);
  const colorEstado = ejecucion?.estado === 'completada' ? 'exito' : ['fallida', 'bloqueada'].includes(ejecucion?.estado) ? 'fallo' : 'proceso';

  return <main className="pagina">
    <header className="cabecera">
      <div className="marca"><span className="marca-icono">C</span><div><strong>AGENTE CIEL LIBRE</strong><small>MODELOS LOCALES · SIN API DE PAGO</small></div></div>
      <div className="cabecera-derecha"><span className="identidad-estudio"><span className="punto" /> Estudio digital <span className="version">v0.8.0</span></span><div className="selector-tema" role="group" aria-label="Tema de la interfaz"><button type="button" aria-pressed={tema === 'claro'} onClick={() => cambiarTema('claro')}><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" /></svg>Claro</button><button type="button" aria-pressed={tema === 'oscuro'} onClick={() => cambiarTema('oscuro')}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.5 14A8.5 8.5 0 0 1 10 3.5 8.5 8.5 0 1 0 20.5 14Z" /></svg>Oscuro</button></div></div>
    </header>

    <nav className="navegacion" aria-label="Páginas del estudio">{Object.entries(paginas).map(([clave, [titulo]]) => <a key={clave}
      href={`#/${clave}${clave === 'resultado' && identificador ? `/${identificador}` : ''}`}
      aria-current={ruta.pagina === clave ? 'page' : undefined}>{titulo}</a>)}</nav>
    <section className="encabezado-pagina"><p className="ceja">ESTUDIO CAD DIGITAL</p><h1>{paginas[ruta.pagina][0]}</h1><p>{paginas[ruta.pagina][1]}</p></section>

    {ruta.pagina === 'historial' && <Historial />}
    {ruta.pagina === 'generar' && <div className="pagina-generacion">
      <section className="tarjeta formulario">
        <div className="titulo-seccion"><span className="numero">01</span><div><h2>Nueva generación</h2><p>Define la pieza y el entorno de construcción.</p></div></div>
        <form onSubmit={iniciar}>
          <label htmlFor="descripcion">DESCRIPCIÓN DE LA PIEZA</label>
          {casoSeleccionado && <p className="nota-campana">Caso {casoSeleccionado.codigo} · {casoSeleccionado.nivel}. <button type="button" className="enlace-boton" onClick={() => cambiarCasoSeleccionado(null)}>Quitar asociación</button></p>}
          <textarea id="descripcion" value={descripcion} onChange={(evento) => { cambiarDescripcion(evento.target.value); cambiarCasoSeleccionado(null); }} minLength={12} maxLength={4000} rows={7} placeholder="Dimensiones en milímetros, agujeros, radios, posiciones y otras restricciones…" required />
          <div className="contador">{descripcion.length} / 4000 caracteres</div>
          <div className="campos"><div><label htmlFor="modelo">MODELO DE IA</label><select id="modelo" value={modelo} onChange={(evento) => cambiarModelo(evento.target.value)} required><option value="">Selecciona un modelo</option><OpcionesModelos modelos={opciones?.modelos || nombresModelo} /></select></div></div>
          <div className="campos"><div><label htmlFor="motor">MOTOR CAD</label><select id="motor" value={motor} onChange={(evento) => cambiarMotor(evento.target.value)}>{Object.entries(opciones?.motores || nombresMotor).map(([clave, nombre]) => <option value={clave} key={clave}>{nombre}</option>)}</select></div><div><label htmlFor="modo">ESTRATEGIA</label><select id="modo" value={modo} onChange={(evento) => cambiarModo(evento.target.value)}><option value="open-loop">Open-loop · una generación</option><option value="closed-loop">Closed-loop · hasta cinco</option></select></div></div>
          <div className="nota">{modo === 'closed-loop' ? <>Hasta <strong>5 generaciones totales</strong>: una inicial y cuatro correcciones si son necesarias.</> : <><strong>Una generación</strong> sin feedback ni corrección.</>} Se detiene al obtener CAD válido y exportable. La inferencia usa tu equipo y puede tardar según sus recursos.</div>
          {error && <p className="error" role="alert">{error}</p>}
          <button className="boton" disabled={enviando || !modelo || descripcion.trim().length < 12}>{enviando ? 'Iniciando…' : 'Generar pieza 3D'} <span>↗</span></button>
        </form>
      </section>
      <aside className="guia-generacion"><h2>Tu pieza, paso a paso</h2><ol><li>Describe las dimensiones, curvas y detalles que necesitas.</li><li>Elige un modelo local instalado. No requiere cuentas ni claves de API.</li><li>Selecciona el motor CAD y la estrategia de generación.</li></ol><p>El resultado se abrirá en su propia página con el visor 360°, los archivos y el diagnóstico de cada intento.</p><a href="#/casos">Explorar e importar prompts →</a>{identificador && <a href={`#/resultado/${identificador}`}>Ver la última ejecución →</a>}</aside>
    </div>}

    {ruta.pagina === 'resultado' && <div className="pagina-resultado">
      <section className="tarjeta resultado">
        <div className="titulo-seccion"><span className="numero">02</span><div><h2>Resultado de la ejecución</h2><p>Estado, diagnósticos y entregables.</p></div></div>
        {problemaResultado && <p className="error" role="alert">{problemaResultado}</p>}
        {!ejecucion && <div className="vacio"><div className="vacio-cubo">◇</div><strong>{identificador ? 'Consultando la ejecución' : 'Aún no hay una pieza'}</strong><p>{identificador ? 'El resultado aparecerá aquí cuando la ejecución esté disponible.' : 'Al iniciar una generación verás aquí los intentos, la vista previa y los archivos.'}</p></div>}
        {ejecucion && <>
          <div className={`estado ${colorEstado}`}><span>{ejecucion.estado === 'completada' ? '✓' : ejecucion.estado === 'generando' || ejecucion.estado === 'pendiente' ? '◌' : '!'}</span><div><strong>{ejecucion.estado === 'completada' ? 'Pieza generada' : ejecucion.estado === 'fallida' ? 'Sin CAD válido' : ejecucion.estado === 'bloqueada' ? 'Ejecución interrumpida' : 'Generando y validando'}</strong><small>{ejecucion.mensaje}</small></div></div>
          <AccionesTrabajo key={ejecucion.identificador + '-' + ejecucion.numero_intentos} ejecucion={ejecucion} modelos={opciones?.modelos} alActualizar={async () => {
            const respuesta = await fetch(`/api/ejecuciones/${ejecucion.identificador}`);
            if (!respuesta.ok) throw new Error('No se pudo actualizar el resultado.');
            cambiarEjecucion(await respuesta.json());
          }} />
          <p className="descripcion-resultado">{ejecucion.descripcion}</p>
          <div className="resumen"><div><small>MOTOR</small><strong>{nombresMotor[ejecucion.motor]}</strong></div><div><small>MODELO</small><strong>{opciones?.modelos?.[ejecucion.modelo] || nombresModelo[ejecucion.modelo] || ejecucion.modelo}</strong></div><div><small>INTENTOS</small><strong>{ejecucion.numero_intentos} / {ejecucion.modo === 'open-loop' ? 1 : 5}</strong></div></div>
          {activo && <div className="barra"><span /></div>}
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
    <footer>AGENTE CIEL LIBRE · ESTUDIO DIGITAL · CADQUERY / BUILD123D / FREECAD</footer>
  </main>;
}

createRoot(document.getElementById('raiz')).render(<Aplicacion />);
