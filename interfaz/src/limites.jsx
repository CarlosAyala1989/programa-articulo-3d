import React from 'react';

export default function LimitesModelo({ modelo, opciones }) {
  const limites = opciones?.limites_por_modelo?.[modelo];
  if (!limites) return null;
  const numero = (valor) => Number(valor).toLocaleString('es-PE');
  return <div className="nota limites-modelo">
    <strong>Límites oficiales de referencia: </strong>
    {limites.entrada ? `entrada ${numero(limites.entrada)}` : limites.contexto ? `contexto compartido ${numero(limites.contexto)}` : 'contexto gestionado por el proveedor'}
    {limites.salida && ` · salida ${numero(limites.salida)}`} tokens.
    {limites.gestion === 'cli'
      ? ' La suscripción y el CLI controlan los límites efectivos; la aplicación envía el texto completo y no añade un tope de tokens.'
      : limites.salida_configurada
        ? ' Salida configurada al máximo publicado. La entrada y el historial consumen contexto; no se recortan.'
        : ' Sin recorte de texto por la aplicación; máximo de esta ruta pendiente de verificar.'}
    {limites.fuentes?.length > 0 && <> <a href={limites.fuentes[0]} target="_blank" rel="noreferrer">Fuente oficial</a></>}
  </div>;
}
