import React from 'react';

export const nombresEsfuerzo = { low: 'Bajo', medium: 'Medio', high: 'Alto', xhigh: 'Muy alto', max: 'Máximo' };
const modelosDeepSeek = ['deepseek-flash', 'deepseek-v4-pro'];
const esfuerzosDeepSeek = { low: 'Bajo', high: 'Alto', max: 'Máximo' };

export function nivelesEsfuerzo(opciones, modelo) {
  const niveles = opciones?.esfuerzos_por_modelo?.[modelo] || (modelosDeepSeek.includes(modelo) ? esfuerzosDeepSeek : null);
  return niveles && Object.keys(niveles).length ? niveles : null;
}

export function valorEsfuerzo(opciones, modelo, preferido) {
  const niveles = nivelesEsfuerzo(opciones, modelo);
  if (!niveles) return null;
  if (preferido && niveles[preferido]) return preferido;
  const predeterminado = opciones?.esfuerzos_predeterminados?.[modelo] || (modelosDeepSeek.includes(modelo) ? 'max' : null);
  return niveles[predeterminado] ? predeterminado : Object.keys(niveles)[0];
}

export default function CampoEsfuerzo({ identificador, modelo, opciones, valor, alCambiar, etiqueta = 'NIVEL DE ESFUERZO' }) {
  const niveles = nivelesEsfuerzo(opciones, modelo);
  const detalle = opciones?.detalles_esfuerzo?.[modelo];
  const habilitado = Boolean(modelo && niveles);
  const fijo = detalle?.esfuerzo_informado;
  const ayuda = !modelo ? 'Selecciona un modelo para habilitar este campo.'
    : !niveles ? detalle?.esfuerzo_ajustable === false ? 'El CLI no permite ajustar el esfuerzo de este modelo.'
      : 'Este modelo no anuncia niveles de esfuerzo seleccionables. Elige un modelo concreto para consultar sus niveles.'
      : detalle?.modelos_por_esfuerzo ? 'Cambiar el esfuerzo selecciona la variante exacta del modelo. Se conserva en sus correcciones.'
        : 'Se mantiene en la generación inicial y en sus correcciones. Un nivel mayor puede tardar más y consumir más cuota.';
  return <div>
    <label htmlFor={identificador}>{etiqueta}</label>
    <select id={identificador} value={habilitado ? valorEsfuerzo(opciones, modelo, valor) : ''} disabled={!habilitado}
      onChange={(evento) => alCambiar(evento.target.value)} aria-describedby={`${identificador}-ayuda`} required={habilitado}>
      {!habilitado && <option value="">{!modelo ? 'Selecciona un modelo primero' : fijo ? `${nombresEsfuerzo[fijo] || fijo} · ${fijo} (fijo)` : detalle?.esfuerzo_ajustable === false ? 'No ajustable por este CLI' : 'Sin niveles anunciados'}</option>}
      {habilitado && Object.entries(niveles).map(([clave, nombre]) => <option value={clave} key={clave}>{nombre} · {clave}</option>)}
    </select>
    <small id={`${identificador}-ayuda`} className="ayuda-campo">{ayuda}</small>
  </div>;
}
