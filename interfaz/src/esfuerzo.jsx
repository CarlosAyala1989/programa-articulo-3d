import React from 'react';

export const nombresEsfuerzo = { low: 'Bajo', high: 'Alto', max: 'Máximo' };
const modelosDeepSeek = ['deepseek-flash', 'deepseek-v4-pro'];

export function nivelesEsfuerzo(opciones, modelo) {
  return opciones?.esfuerzos_por_modelo?.[modelo] || (modelosDeepSeek.includes(modelo) ? nombresEsfuerzo : null);
}

export default function CampoEsfuerzo({ identificador, modelo, opciones, valor, alCambiar, campana = false }) {
  const niveles = nivelesEsfuerzo(opciones, modelo);
  const habilitado = Boolean(modelo && niveles);
  const ayuda = !modelo ? 'Selecciona un modelo para habilitar este campo.'
    : !niveles ? 'Este control está disponible para DeepSeek Flash y Pro.'
      : campana ? 'Se aplica a los modelos DeepSeek de esta campaña y a todos sus intentos.'
        : 'Se mantiene en la generación inicial y en sus correcciones.';
  return <div>
    <label htmlFor={identificador}>NIVEL DE ESFUERZO</label>
    <select id={identificador} value={habilitado ? valor : ''} disabled={!habilitado}
      onChange={(evento) => alCambiar(evento.target.value)} aria-describedby={`${identificador}-ayuda`} required={habilitado}>
      {!habilitado && <option value="">{modelo ? 'No disponible para este modelo' : 'Selecciona un modelo primero'}</option>}
      {habilitado && Object.entries(niveles).map(([clave, nombre]) => <option value={clave} key={clave}>{nombre} · {clave}</option>)}
    </select>
    <small id={`${identificador}-ayuda`} className="ayuda-campo">{ayuda}</small>
  </div>;
}
