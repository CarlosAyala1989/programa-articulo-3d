#!/usr/bin/env bash
set -Eeuo pipefail
export CIEL_DIRECTORIO_RESULTADOS="$(cat /opt/agente-ciel-libre/ruta-resultados.txt)"
[[ -f /etc/agente-ciel-libre ]] || exit 1
systemctl start docker ciel-ollama
export OLLAMA_HOST=http://172.17.0.1:11436
cd /opt/agente-ciel-libre/programa
for INTENTO in $(seq 1 60); do
  if curl --fail --silent "$OLLAMA_HOST/api/tags" >/dev/null; then break; fi
  sleep 2
done
curl --fail --silent "$OLLAMA_HOST/api/tags" >/dev/null
python3 preparar_modelos.py --verificar
docker compose up -d
for INTENTO in $(seq 1 90); do
  if curl --silent --fail http://127.0.0.1:8010/api/salud >/dev/null; then exit 0; fi
  sleep 2
done
printf 'El servicio no respondió. Consulta el diagnóstico de la instalación.\n' >&2
exit 1
