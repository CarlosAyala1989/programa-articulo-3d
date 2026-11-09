import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { TrackballControls } from 'three/addons/controls/TrackballControls.js';
import './metrologia.css';

async function pedir(url, opciones) {
  const respuesta = await fetch(url, opciones);
  const datos = await respuesta.json();
  if (!respuesta.ok) {
    const detalle = typeof datos.detail === 'string' ? datos.detail : datos.detail?.map((e) => `${e.loc.at(-1)}: ${e.msg}`).join(' · ');
    throw new Error(detalle || 'No se pudo completar la operación. Vuelve a intentarlo.');
  }
  return datos;
}

const numero = (valor, unidad = '') => valor == null ? 'No medido' : `${Number(valor).toLocaleString('es', { maximumFractionDigits: 4 })}${unidad ? ` ${unidad}` : ''}`;

function ubicacionCota(cota) {
  if (!cota) return '';
  const eje = cota.eje.map((v, i) => Math.abs(v) > .9999 ? 'XYZ'[i] : null).find(Boolean)
    || `(${cota.eje.map((v) => numero(v)).join('; ')})`;
  if (cota.tipo === 'diametro') {
    const z = (cota.limites_z[0] + cota.limites_z[1]) / 2;
    const centro = cota.base.map((fila) => fila[0] * cota.centro_xy[0] + fila[1] * cota.centro_xy[1] + fila[2] * z);
    return `Centro ${centro.map((v, i) => `${'XYZ'[i]}=${numero(v)}`).join('; ')} mm · eje ${eje}`;
  }
  return `Eje ${eje} · planos a ${cota.regiones.map((r) => numero(r.posicion)).join(' y ')} mm del origen`;
}

function VisorComparacion({ identificador, modo }) {
  const contenedor = useRef(null);
  const [error, cambiarError] = useState('');
  useEffect(() => {
    const elemento = contenedor.current;
    let activo = true;
    const objetos = [];
    let cuadro, renderizador, controles, observador;
    const limpiar = () => {
      activo = false; cancelAnimationFrame(cuadro); observador?.disconnect(); controles?.dispose();
      objetos.forEach((o) => { o.geometry.dispose(); o.material.dispose(); });
      renderizador?.dispose(); renderizador?.domElement.remove();
    };
    async function iniciar() {
      cambiarError('');
      try {
        const base = `/api/comparaciones-fisicas/${identificador}/archivos/`;
        const [geometria, datos] = await Promise.all([new STLLoader().loadAsync(`${base}nominal.stl`), pedir(`${base}vista.json`)]);
        if (!activo) { geometria.dispose(); return; }
        renderizador = new THREE.WebGLRenderer({ antialias: true, alpha: true });
        renderizador.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        elemento.appendChild(renderizador.domElement);
        const escena = new THREE.Scene();
        const camara = new THREE.PerspectiveCamera(40, 1, .01, 100000);
        controles = new TrackballControls(camara, renderizador.domElement);
        escena.add(new THREE.HemisphereLight(0xffffff, 0x687987, 3));
        geometria.computeVertexNormals(); geometria.computeBoundingBox();
        const centro = geometria.boundingBox.getCenter(new THREE.Vector3());
        const dimension = geometria.boundingBox.getSize(new THREE.Vector3()).length();
        const grupo = new THREE.Group();
        grupo.rotation.x = -Math.PI / 2;
        const malla = new THREE.Mesh(geometria, new THREE.MeshStandardMaterial({
          color: '#8195ab', transparent: modo !== 'nominal', opacity: modo === 'nominal' ? 1 : .22,
          depthWrite: modo === 'nominal', side: THREE.DoubleSide, roughness: .8,
        }));
        malla.visible = modo !== 'desviacion';
        malla.position.copy(centro).multiplyScalar(-1); grupo.add(malla); objetos.push(malla);
        const puntos = new THREE.BufferGeometry();
        puntos.setAttribute('position', new THREE.Float32BufferAttribute(datos.puntos.flatMap((p) => [p[0] - centro.x, p[1] - centro.y, p[2] - centro.z]), 3));
        puntos.setAttribute('color', new THREE.Float32BufferAttribute(datos.colores.flatMap((c) => {
          const color = new THREE.Color().setRGB(c[0] / 255, c[1] / 255, c[2] / 255, THREE.SRGBColorSpace);
          return [color.r, color.g, color.b];
        }), 3));
        const nube = new THREE.Points(puntos, new THREE.PointsMaterial({ vertexColors: modo === 'desviacion',
          color: modo === 'desviacion' ? 0xffffff : '#d45220', size: 3, sizeAttenuation: false }));
        nube.visible = modo !== 'nominal'; grupo.add(nube); objetos.push(nube);
        escena.add(grupo);
        camara.position.set(dimension * 1.1, dimension * .8, dimension * 1.1);
        camara.near = Math.max(dimension / 10000, .001); camara.far = dimension * 100;
        camara.lookAt(0, 0, 0);
        const ajustar = () => {
          camara.aspect = Math.max(elemento.clientWidth, 1) / Math.max(elemento.clientHeight, 1);
          camara.updateProjectionMatrix(); renderizador.setSize(elemento.clientWidth, elemento.clientHeight); controles.handleResize();
        };
        observador = new ResizeObserver(ajustar); observador.observe(elemento); ajustar();
        const animar = () => { if (activo) { cuadro = requestAnimationFrame(animar); controles.update(); renderizador.render(escena, camara); } };
        animar();
      } catch (fallo) { if (activo) cambiarError('No se pudo abrir el visor 3D. Puedes revisar el mapa PNG y descargar los archivos.'); }
    }
    iniciar();
    return limpiar;
  }, [identificador, modo]);
  return <div ref={contenedor} className="visor-metrologia" aria-label={modo === 'desviacion' ? 'Desviaciones 3D del escaneo' : modo === 'superposicion' ? 'Superposición del escaneo y el modelo virtual' : 'Modelo virtual nominal'}>{error && <p role="status">{error}</p>}</div>;
}

const inicial = { pieza: '', unidad: 'mm', impresora: '', material: '', altura_capa_mm: '', parametros_impresion: '',
  fecha_escaneo: '', calibracion_realizada: false, fecha_calibracion: '', notas_calibracion: '', software: 'CrealityScan',
  serie_escaner: '', banda_cotas_mm: .5, tolerancia_mm: .3, umbral_icp_mm: 2, mapa_limite_mm: .5, muestras: 20000, alineacion: 'automatica', notas: '' };

export default function CompararResultado({ ejecucion }) {
  const [datos, cambiarDatos] = useState({ ...inicial, pieza: ejecucion.codigo_prompt || 'Pieza impresa' });
  const [escaneo, cambiarEscaneo] = useState(null);
  const [foto, cambiarFoto] = useState(null);
  const [cotas, cambiarCotas] = useState([]);
  const [pares, cambiarPares] = useState('');
  const [registros, cambiarRegistros] = useState([]);
  const [seleccion, cambiarSeleccion] = useState('');
  const [cargando, cambiarCargando] = useState(true);
  const [ocupado, cambiarOcupado] = useState(false);
  const [fase, cambiarFase] = useState('');
  const [error, cambiarError] = useState('');
  const [perfiles, cambiarPerfiles] = useState([]);
  const [perfil, cambiarPerfil] = useState('');
  const [nombrePerfil, cambiarNombrePerfil] = useState('Mi configuración de impresión y Otter');
  const [plan, cambiarPlan] = useState(null);
  const [codigos, cambiarCodigos] = useState([]);
  const [automaticas, cambiarAutomaticas] = useState(true);
  const [modo, cambiarModo] = useState('desviacion');
  const elegido = registros.find((r) => r.identificador === seleccion) || registros[0];
  const pendientes = registros.some((r) => ['pendiente', 'recibiendo', 'procesando'].includes(r.estado));
  const actualizar = async () => {
    const nuevos = await pedir(`/api/ejecuciones/${ejecucion.identificador}/comparaciones-fisicas`);
    cambiarRegistros(nuevos); return nuevos;
  };
  useEffect(() => {
    let activo = true;
    pedir(`/api/ejecuciones/${ejecucion.identificador}/comparaciones-fisicas`)
      .then((r) => { if (activo) cambiarRegistros(r); })
      .catch((e) => { if (activo) cambiarError(e.message); })
      .finally(() => { if (activo) cambiarCargando(false); });
    return () => { activo = false; };
  }, [ejecucion.identificador]);
  useEffect(() => {
    let activo = true;
    Promise.all([pedir('/api/metrologia/perfiles'), pedir(`/api/ejecuciones/${ejecucion.identificador}/plan-cotas`)])
      .then(([nuevos, p]) => {
        if (!activo) return;
        cambiarPerfiles(nuevos);
        if (nuevos[0]) { cambiarPerfil(nuevos[0].identificador); cambiarDatos((d) => ({ ...d, ...nuevos[0].configuracion })); }
        cambiarPlan(p.documento ? p : null); cambiarCodigos(p.documento?.cotas.map((c) => c.codigo) || []);
      }).catch((e) => { if (activo) cambiarError(e.message); });
    return () => { activo = false; };
  }, [ejecucion.identificador]);
  async function gestionarPlan(seleccionar = false) {
    cambiarOcupado(true); cambiarError(''); cambiarFase('Preparando las regiones de medición del modelo…');
    try {
      const p = await pedir(`/api/ejecuciones/${ejecucion.identificador}/plan-cotas${seleccionar ? '' : '/proponer'}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        ...(seleccionar ? { body: JSON.stringify({ origen_identificador: plan.identificador, codigos }) } : {}) });
      cambiarPlan(p); cambiarCodigos(p.documento.cotas.map((c) => c.codigo));
      cambiarFase('Plan guardado para este modelo. Las comparaciones anteriores conservan su selección.');
    } catch (e) { cambiarError(e.message); cambiarFase(''); }
    finally { cambiarOcupado(false); }
  }
  function elegirPerfil(id) {
    cambiarPerfil(id);
    const elegidoPerfil = perfiles.find((p) => p.identificador === id);
    if (elegidoPerfil) cambiarDatos((d) => ({ ...d, ...elegidoPerfil.configuracion }));
  }
  async function guardarPerfil() {
    cambiarOcupado(true); cambiarError('');
    try {
      const claves = ['serie_escaner', 'software', 'impresora', 'material', 'parametros_impresion', 'unidad'];
      const configuracion = Object.fromEntries(claves.map((k) => [k, datos[k]]));
      ['tolerancia_mm', 'umbral_icp_mm', 'mapa_limite_mm', 'muestras', 'banda_cotas_mm'].forEach((k) => { configuracion[k] = Number(datos[k]); });
      configuracion.altura_capa_mm = datos.altura_capa_mm ? Number(datos.altura_capa_mm) : null;
      const nuevo = await pedir('/api/metrologia/perfiles', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nombre: nombrePerfil, configuracion }) });
      cambiarPerfiles([nuevo, ...perfiles]); cambiarPerfil(nuevo.identificador);
      cambiarFase('Configuración guardada. Se cargará al comparar otra pieza; las fechas y calibraciones se registran por escaneo.');
    } catch (e) { cambiarError(e.message); }
    finally { cambiarOcupado(false); }
  }
  useEffect(() => {
    if (!pendientes) return undefined;
    let activo = true, temporizador;
    async function consultar() {
      try {
        const nuevos = await pedir(`/api/ejecuciones/${ejecucion.identificador}/comparaciones-fisicas`);
        if (activo) cambiarRegistros(nuevos);
      } catch (e) { if (activo) cambiarError(e.message); }
      if (activo) temporizador = setTimeout(consultar, 2500);
    }
    temporizador = setTimeout(consultar, 2500);
    return () => { activo = false; clearTimeout(temporizador); };
  }, [pendientes, ejecucion.identificador]);
  function campo(clave, valor) { cambiarDatos((d) => ({ ...d, [clave]: valor })); }
  function cambiarCota(indice, clave, valor) { cambiarCotas((actuales) => actuales.map((c, i) => i === indice ? { ...c, [clave]: valor } : c)); }
  async function comparar(evento) {
    evento.preventDefault(); cambiarError(''); cambiarOcupado(true); cambiarFase('Guardando los datos de la pieza…');
    try {
      if (!escaneo) throw new Error('Selecciona el archivo exportado desde CrealityScan.');
      if (escaneo.size > 250 * 1024 * 1024) throw new Error('El escaneo supera los 250 MB. Reduce la malla al exportar desde CrealityScan.');
      const medidas = cotas.map((c) => ({ nombre: c.nombre, nominal_mm: Number(c.nominal_mm), metodo: c.metodo,
        mediciones_mm: c.mediciones.split(';').map((v) => Number(v.trim().replace(',', '.'))) }));
      if (medidas.some((c) => !c.nombre.trim() || !(c.nominal_mm > 0) || c.mediciones_mm.some((v) => !Number.isFinite(v) || v <= 0))) {
        throw new Error('Completa las cotas con medidas positivas, separadas por punto y coma.');
      }
      const puntosPareados = datos.alineacion !== 'puntos' ? [] : pares.trim().split('\n').filter(Boolean).map((linea) => {
        const [a, b] = linea.split('|');
        const xyz = (v) => (v || '').trim().split(/[\s,]+/).map(Number);
        return { escaneo: xyz(a), nominal: xyz(b) };
      });
      const solicitud = { ...datos, medir_cotas_automaticas: automaticas,
        plan_identificador: automaticas ? plan?.identificador || null : null, perfil_identificador: perfil || null,
        banda_cotas_mm: Number(datos.banda_cotas_mm), altura_capa_mm: datos.altura_capa_mm ? Number(datos.altura_capa_mm) : null,
        fecha_escaneo: datos.fecha_escaneo || null, fecha_calibracion: datos.fecha_calibracion || null,
        tolerancia_mm: Number(datos.tolerancia_mm), umbral_icp_mm: Number(datos.umbral_icp_mm),
        mapa_limite_mm: Number(datos.mapa_limite_mm), muestras: Number(datos.muestras), cotas: medidas, puntos_pareados: puntosPareados };
      const creado = await pedir(`/api/ejecuciones/${ejecucion.identificador}/comparaciones-fisicas`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(solicitud) });
      if (foto) {
        cambiarFase('Guardando la fotografía…');
        await pedir(`/api/comparaciones-fisicas/${creado.identificador}/foto`, { method: 'PUT', body: foto });
      }
      cambiarFase('Cargando el escaneo…');
      await pedir(`/api/comparaciones-fisicas/${creado.identificador}/escaneo?nombre=${encodeURIComponent(escaneo.name)}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/octet-stream' }, body: escaneo });
      cambiarSeleccion(creado.identificador); await actualizar(); cambiarFase('Escaneo recibido. La comparación continúa en segundo plano.');
    } catch (fallo) { cambiarError(fallo.message); cambiarFase(''); }
    finally { cambiarOcupado(false); }
  }
  async function accion(nombre) {
    cambiarError(''); cambiarOcupado(true);
    try { await pedir(`/api/comparaciones-fisicas/${elegido.identificador}/${nombre}`, { method: 'POST' }); await actualizar(); }
    catch (e) { cambiarError(e.message); }
    finally { cambiarOcupado(false); }
  }
  const resultado = elegido?.resultado;
  const base = elegido ? `/api/comparaciones-fisicas/${elegido.identificador}` : '';
  return <details className="metrologia" open={window.location.hash.endsWith('/comparar') ? true : undefined}>
    <summary><strong>Comparar resultado con una pieza escaneada</strong></summary>
    <p>Imprime la pieza por tu cuenta y escanéala con tu CR-Scan Otter. Aquí podrás comparar su geometría con el modelo virtual guardado.</p>
    <details className="nueva-medicion" open={registros.length === 0 ? true : undefined}><summary><strong>Cargar un nuevo escaneo</strong></summary>
    <form onSubmit={comparar} className="formulario-metrologia">
      <fieldset disabled={ocupado}>
        <legend>Nueva comparación</legend>
        <details><summary>Configuración reutilizable</summary>
          <p>El perfil más reciente se carga al abrir otra pieza. Guarda aquí tu impresora, material y parámetros de comparación.</p>
          <label>Perfil<select value={perfil} onChange={(e) => elegirPerfil(e.target.value)}><option value="">Configuración actual sin perfil</option>{perfiles.map((p) => <option key={p.identificador} value={p.identificador}>{p.nombre}</option>)}</select></label>
          <div className="campos-metrologia"><label>Nombre del nuevo perfil<input maxLength={100} value={nombrePerfil} onChange={(e) => cambiarNombrePerfil(e.target.value)} /></label><div className="acciones-perfil"><button type="button" disabled={!nombrePerfil.trim()} onClick={guardarPerfil}>Guardar configuración actual</button></div></div>
          <small>Cada guardado crea un perfil nuevo. Las medidas, fechas y calibraciones se registran para cada escaneo.</small>
        </details>
        <div className="campos-metrologia">
          <label>Nombre de la pieza o réplica<input required maxLength={120} value={datos.pieza} onChange={(e) => campo('pieza', e.target.value)} /></label>
          <label>Archivo del escáner<input type="file" required accept=".stl,.obj,.ply,.pcd,.asc,.xyz" onChange={(e) => cambiarEscaneo(e.target.files[0] || null)} /><small>STL, OBJ o PLY de CrealityScan; también PCD, ASC y XYZ. Hasta 250 MB.</small></label>
          <label>Unidades del archivo<select value={datos.unidad} onChange={(e) => campo('unidad', e.target.value)}><option value="mm">Milímetros (mm)</option><option value="cm">Centímetros (cm)</option><option value="m">Metros (m)</option><option value="in">Pulgadas (in)</option></select><small>El tamaño se convierte a mm; la alineación conserva esa escala.</small></label>
          <label>Foto de la pieza impresa (opcional)<input type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => cambiarFoto(e.target.files[0] || null)} /><small>Se incluirá junto al render virtual en la matriz fotográfica.</small></label>
        </div>
        <details><summary>Impresión, escaneo y calibración</summary><div className="campos-metrologia">
          <label>Impresora<input maxLength={100} value={datos.impresora} onChange={(e) => campo('impresora', e.target.value)} placeholder="Ej. Bambu Lab X1 Carbon" /></label>
          <label>Material<input maxLength={100} value={datos.material} onChange={(e) => campo('material', e.target.value)} placeholder="Ej. PLA, fabricante y lote" /></label>
          <label>Altura de capa (mm)<input type="number" min="0.001" max="10" step="any" value={datos.altura_capa_mm} onChange={(e) => campo('altura_capa_mm', e.target.value)} /></label>
          <label>Fecha del escaneo<input type="date" value={datos.fecha_escaneo} onChange={(e) => campo('fecha_escaneo', e.target.value)} /></label>
          <label>Versión de CrealityScan<input maxLength={100} value={datos.software} onChange={(e) => campo('software', e.target.value)} /></label>
          <label>Número de serie del Otter<input maxLength={100} value={datos.serie_escaner} onChange={(e) => campo('serie_escaner', e.target.value)} /></label>
          <label className="opcion-check"><input type="checkbox" checked={datos.calibracion_realizada} onChange={(e) => campo('calibracion_realizada', e.target.checked)} />Escáner calibrado antes de la medición</label>
          <label>Fecha de calibración<input type="date" required={datos.calibracion_realizada} value={datos.fecha_calibracion} onChange={(e) => campo('fecha_calibracion', e.target.value)} /></label>
        </div><label>Registro de calibración<textarea maxLength={1000} value={datos.notas_calibracion} onChange={(e) => campo('notas_calibracion', e.target.value)} placeholder="Placa utilizada y resultado de la comprobación" /></label><label>Otros parámetros de impresión<textarea maxLength={2000} value={datos.parametros_impresion} onChange={(e) => campo('parametros_impresion', e.target.value)} placeholder="Boquilla, temperaturas, relleno, orientación, soportes y perfil del laminador" /></label></details>
        <details open><summary>Cotas automáticas del escaneo</summary>
          <label className="opcion-check"><input type="checkbox" checked={automaticas} onChange={(e) => cambiarAutomaticas(e.target.checked)} />Medir diámetros y separaciones entre planos</label>
          <p>{plan ? `${plan.documento.cotas.length} cotas guardadas para este modelo.` : 'Al cargar el primer escaneo se detectarán las cotas del modelo. También puedes prepararlas ahora.'} Revisa cuáles corresponden a las cotas críticas de tu pieza.</p>
          {automaticas && <><button type="button" onClick={() => gestionarPlan(false)}>{plan ? 'Volver a detectar todas las cotas' : 'Detectar cotas del modelo'}</button>
          {plan && <><p>{plan.documento.limites}</p><p>Las ubicaciones se expresan en las coordenadas del modelo virtual, en milímetros.</p><div className="seleccion-cotas">{plan.documento.cotas.map((c) => <label className="opcion-check" key={c.codigo}><input type="checkbox" checked={codigos.includes(c.codigo)} onChange={() => cambiarCodigos(codigos.includes(c.codigo) ? codigos.filter((k) => k !== c.codigo) : [...codigos, c.codigo])} /><span>{c.codigo} · {c.nombre} · {numero(c.nominal_mm, 'mm')}<small className="ubicacion-cota">{ubicacionCota(c)}</small></span></label>)}</div>
          <button type="button" disabled={!codigos.length} onClick={() => gestionarPlan(true)}>Guardar selección de cotas críticas</button>
          {plan.documento.cotas.length > 0 && codigos.length !== plan.documento.cotas.length && <p role="status">Guarda la selección antes de comparar para aplicar este cambio.</p>}
          {!plan.documento.cotas.length && <p role="status">No se detectaron planos opuestos ni cilindros completos. Añade medidas complementarias para estas cotas.</p>}</>}
          <label>Banda de asociación de las cotas (mm)<input type="number" required min="0.01" max="10" step="any" value={datos.banda_cotas_mm} onChange={(e) => campo('banda_cotas_mm', e.target.value)} /><small>Desviación máxima esperada alrededor de cada región nominal. Una banda grande puede incluir superficies vecinas.</small></label></>}
        </details>
        <details><summary>Medidas complementarias con instrumento (opcional)</summary>
          <p>Registra las cotas que mediste con calibre o en el escaneo. El error ΔD se calcula como medida menos nominal. La envolvente automática del modelo se informa por separado.</p>
          {cotas.map((cota, i) => <div className="fila-cota" key={i}>
            <label>Cota<input required value={cota.nombre} maxLength={100} onChange={(e) => cambiarCota(i, 'nombre', e.target.value)} placeholder="Diámetro del agujero" /></label>
            <label>Nominal (mm)<input required type="number" min="0.0001" step="any" value={cota.nominal_mm} onChange={(e) => cambiarCota(i, 'nominal_mm', e.target.value)} /></label>
            <label>Mediciones (mm), separadas por ;<input required value={cota.mediciones} onChange={(e) => cambiarCota(i, 'mediciones', e.target.value)} placeholder="8.02; 8.04; 8.03" /></label>
            <label>Método o instrumento<input required minLength={3} maxLength={150} value={cota.metodo} onChange={(e) => cambiarCota(i, 'metodo', e.target.value)} placeholder="Calibre o medición en CrealityScan" /></label>
            <button type="button" onClick={() => cambiarCotas(cotas.filter((_, j) => i !== j))}>Quitar cota {i + 1}</button>
          </div>)}
          <button type="button" disabled={cotas.length >= 30} onClick={() => cambiarCotas([...cotas, { nombre: '', nominal_mm: '', mediciones: '', metodo: '' }])}>Añadir cota crítica</button>
        </details>
        <details><summary>Alineación y parámetros de comparación</summary><p>Exporta únicamente la pieza desde CrealityScan, sin mesa ni soportes ajenos. Si la alineación automática no coincide, utiliza puntos correspondientes.</p><div className="campos-metrologia">
          <label>Alineación<select value={datos.alineacion} onChange={(e) => campo('alineacion', e.target.value)}><option value="automatica">Automática · orientación inicial + ICP</option><option value="conservar">El archivo ya está alineado · conservar posición</option><option value="puntos">Puntos correspondientes + ICP</option></select></label>
          <label>Tolerancia de comparación (mm)<input required type="number" min="0.0001" max="100" step="any" value={datos.tolerancia_mm} onChange={(e) => campo('tolerancia_mm', e.target.value)} /></label>
          <label>Umbral final ICP y cobertura (mm)<input required type="number" min="0.001" max="1000" step="any" value={datos.umbral_icp_mm} onChange={(e) => campo('umbral_icp_mm', e.target.value)} /></label>
          <label>Límite de color del mapa (mm)<input required type="number" min="0.0001" max="100" step="any" value={datos.mapa_limite_mm} onChange={(e) => campo('mapa_limite_mm', e.target.value)} /></label>
          <label>Muestras por superficie<input required type="number" min="2000" max="100000" step="1000" value={datos.muestras} onChange={(e) => campo('muestras', e.target.value)} /></label>
        </div>{datos.alineacion === 'puntos' && <label>Pares XYZ: escaneo | modelo nominal<textarea required rows={5} value={pares} onChange={(e) => cambiarPares(e.target.value)} placeholder={'10 0 0 | 0 0 0\n20 0 0 | 10 0 0\n10 10 0 | 0 10 0'} /><small>Al menos tres pares no colineales. Escaneo en sus unidades de entrada; nominal en mm.</small></label>}</details>
        <label>Notas de la medición<textarea maxLength={4000} value={datos.notas} onChange={(e) => campo('notas', e.target.value)} /></label>
        <button className="boton" type="submit" disabled={ocupado || !escaneo || (automaticas && plan && codigos.length !== plan.documento.cotas.length)}>{ocupado ? 'Cargando…' : 'Comparar escaneo con este modelo'}</button>
      </fieldset>
    </form></details>
    {fase && <p role="status">{fase}</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {cargando && <p role="status">Consultando comparaciones anteriores…</p>}
    {!cargando && registros.length === 0 && <p className="nota-metrologia">Todavía no hay mediciones físicas para esta pieza.</p>}
    {registros.length > 0 && <section className="resultados-metrologia" aria-label="Comparaciones físicas guardadas">
      <label>Comparación guardada<select value={elegido?.identificador || ''} onChange={(e) => cambiarSeleccion(e.target.value)}>{registros.map((r) => <option key={r.identificador} value={r.identificador}>{r.configuracion.pieza} · {r.estado} · {r.identificador.slice(0, 8)}</option>)}</select></label>
      <p role="status">{elegido.alineacion_confirmada ? 'Alineación revisada y confirmada.' : elegido.diagnostico || (elegido.estado === 'borrador' ? 'Carga incompleta: crea una nueva comparación con tu archivo.' : elegido.estado)}</p>
      {['pendiente', 'procesando', 'recibiendo'].includes(elegido.estado) && <progress aria-label="Procesando comparación física" />}
      {elegido.estado === 'fallida' && elegido.escaneo_sha256 && <button type="button" disabled={ocupado} onClick={() => accion('reintentar')}>Reintentar comparación</button>}
      {resultado && <>
        <div className="acciones" role="group" aria-label="Vista de la comparación">{[['desviacion', 'Desviaciones'], ['superposicion', 'Superposición'], ['nominal', 'Modelo virtual']].map(([clave, etiqueta]) => <button key={clave} type="button" aria-pressed={modo === clave} onClick={() => cambiarModo(clave)}>{etiqueta}</button>)}</div>
        <VisorComparacion identificador={elegido.identificador} modo={modo} />
        <p className="leyenda-metrologia">{modo === 'desviacion'
          ? (resultado.mapa_firmado ? `Azul: interior · verde: cero · rojo: exterior. Escala −${numero(resultado.mapa_limite_mm)} a +${numero(resultado.mapa_limite_mm)} mm.` : `Verde: cero · rojo: ${numero(resultado.mapa_limite_mm, 'mm')}. Desviaciones absolutas.`)
          : modo === 'superposicion' ? 'Gris: modelo virtual · naranja: escaneo alineado. Se conserva el tamaño de la pieza.' : 'Modelo virtual nominal guardado. Esta vista muestra únicamente la geometría de referencia.'} Arrastra para girar y usa la rueda para acercar.</p>
        <dl className="medidas-metrologia">
          <div><dt>{resultado.hausdorff_alcance ? 'Hausdorff discreto máximo' : 'Hausdorff máximo estimado'}</dt><dd>{numero(resultado.hausdorff_maximo_mm, 'mm')}</dd></div>
          <div><dt>P95 de superficie muestreada</dt><dd>{numero(resultado.hausdorff_p95_mm, 'mm')}</dd></div>
          <div><dt>Chamfer físico cuadrático</dt><dd>{numero(resultado.chamfer_fisico_mm2, 'mm²')}</dd></div>
          <div><dt>Desviación absoluta media</dt><dd>{numero(resultado.desviacion_absoluta_media_mm, 'mm')}</dd></div>
          <div><dt>Dentro de ±{numero(resultado.tolerancia_mm)} mm</dt><dd>{numero(resultado.dentro_tolerancia_pct, '%')}</dd></div>
          <div><dt>Cobertura del nominal a {numero(elegido.configuracion.umbral_icp_mm)} mm</dt><dd>{numero(resultado.cobertura_nominal_pct, '%')}</dd></div>
        </dl>
        <p>{resultado.muestras_escaneo.toLocaleString()} muestras del escaneo y {resultado.muestras_nominal.toLocaleString()} del nominal. Escala de ajuste: 1. Calibración: {elegido.configuracion.calibracion_realizada ? elegido.configuracion.fecha_calibracion : 'sin registrar'}.</p>
        {resultado.hausdorff_alcance && <p>{resultado.hausdorff_alcance}. {resultado.puntos_hausdorff_escaneo.toLocaleString()} puntos del escaneo y {resultado.puntos_hausdorff_nominal.toLocaleString()} del nominal. Máximo de superficie muestreada: {numero(resultado.hausdorff_superficie_muestreado_mm, 'mm')}.</p>}
        {resultado.cotas_automaticas && <>
          <p>ΔD medio: <strong>{numero(resultado.error_dimensional.delta_media_mm, 'mm')}</strong> · desviación entre cotas: <strong>{numero(resultado.error_dimensional.delta_desviacion_estandar_mm, 'mm')}</strong>. {resultado.error_dimensional.cotas_medidas} de {resultado.error_dimensional.cotas_planificadas} cotas medidas. Una sola medida por cota no estima repetibilidad.</p>
          <div className="tabla-contenedor"><table><caption>Cotas medidas automáticamente en el escaneo</caption><thead><tr><th scope="col">Cota</th><th scope="col">Nominal</th><th scope="col">Escaneo</th><th scope="col">ΔD</th><th scope="col">Residuo del ajuste</th><th scope="col">Estado</th></tr></thead><tbody>{resultado.cotas_automaticas.map((c) => <tr key={c.codigo}><th scope="row">{c.codigo} · {c.nombre}<small className="ubicacion-cota">{ubicacionCota(elegido.configuracion.plan_cotas?.cotas.find((nominal) => nominal.codigo === c.codigo))}</small></th><td>{numero(c.nominal_mm, 'mm')}</td><td>{numero(c.medido_mm, 'mm')}</td><td>{numero(c.delta_mm, 'mm')}</td><td>{numero(c.residuo_ajuste_rmse_mm, 'mm')}</td><td>{c.estado === 'medida' ? `${c.n_puntos} puntos` : c.diagnostico}</td></tr>)}</tbody></table></div>
        </>}
        {resultado.cotas_criticas?.length > 0 && <div className="tabla-contenedor"><table><caption>Errores de las cotas críticas declaradas</caption><thead><tr><th scope="col">Cota</th><th scope="col">Nominal</th><th scope="col">Medida media</th><th scope="col">ΔD medio</th><th scope="col">Desv. estándar</th><th scope="col">Método / n</th></tr></thead><tbody>{resultado.cotas_criticas.map((c, i) => <tr key={i}><th scope="row">{c.nombre}</th><td>{numero(c.nominal_mm, 'mm')}</td><td>{numero(c.medido_media_mm, 'mm')}</td><td>{numero(c.delta_media_mm, 'mm')}</td><td>{numero(c.delta_desviacion_estandar_mm, 'mm')}</td><td>{c.metodo} / {c.n}</td></tr>)}</tbody></table></div>}
        {!resultado.cotas_criticas?.length && !resultado.cotas_automaticas?.length && <p>No se registraron cotas críticas. ΔD y su desviación estándar quedan como no medidos.</p>}
        <details><summary>Envolvente y límites del cálculo</summary><p>La envolvente incluye toda la geometría escaneada y puede verse afectada por puntos aislados.</p><ul>{resultado.envolvente_mm.map((e) => <li key={e.eje}>Eje {e.eje}: nominal {numero(e.nominal_mm, 'mm')}, escaneo {numero(e.escaneo_mm, 'mm')}, Δ {numero(e.delta_mm, 'mm')}</li>)}</ul><ul>{resultado.limitaciones.map((l) => <li key={l}>{l}</li>)}</ul></details>
        {!elegido.alineacion_confirmada ? <button type="button" disabled={ocupado} onClick={() => accion('confirmar')}>He revisado y confirmo la alineación</button> : <p className="confirmacion-metrologia">Alineación revisada y confirmada. El CAD original y sus métricas digitales se conservan.</p>}
        <div className="enlaces-metrologia"><a href={`${base}/archivos/mapa-desviacion.png`}>Mapa de desviación PNG</a><a href={`${base}/archivos/escaneo-alineado-colores.ply`}>Escaneo alineado PLY</a><a href={`${base}/archivos/distancias.csv`}>Distancias CSV</a>{elegido.archivos.some((a) => a.nombre === 'comparacion-fotografica.png') && <a href={`${base}/archivos/comparacion-fotografica.png`}>Render y fotografía</a>}<a href={`${base}/entregables.zip`}>Descargar comparación completa</a></div>
        <a href={`${base}/archivos/mapa-desviacion.png`}><img className="mapa-metrologia" loading="lazy" src={`${base}/archivos/mapa-desviacion.png`} alt="Mapa de desviaciones de cuatro vistas con escala en milímetros" /></a>
      </>}
    </section>}
  </details>;
}
