#!/usr/bin/env bash
# Se ejecuta como root exclusivamente en la distribución WSL privada.
set -Eeuo pipefail
export CIEL_DIRECTORIO_RESULTADOS="$(cat /opt/agente-ciel-libre/ruta-resultados.txt)"
trap 'printf "No se pudo completar la etapa Linux (línea %s). Vuelve a abrir Agente Ciel Libre para reanudar.\n" "$LINENO" >&2' ERR
export DEBIAN_FRONTEND=noninteractive
PROGRAMA=/opt/agente-ciel-libre/programa
ESTADO=/var/lib/agente-ciel
mkdir -p "$ESTADO/descargas"
cd "$PROGRAMA"

if [[ ! -f /etc/agente-ciel-libre ]]; then
  printf 'Esta distribución no pertenece a Agente Ciel Libre.\n' >&2
  exit 1
fi

if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  printf 'Instalando el runtime privado: Python, Docker Engine y Compose.\n'
  apt-get update
  apt-get install -y --no-install-recommends ca-certificates curl gnupg python3 zstd
  install -m 0755 -d /etc/apt/keyrings
  curl --fail --location --retry 5 https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  printf 'deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable\n' > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y --no-install-recommends docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker

readarray -t OLLAMA_DEPENDENCIA < <(python3 - <<'PY'
import json
datos=json.load(open('/opt/agente-ciel-libre/dependencias.json'))['ollama']
print(datos['url']);print(datos['sha256']);print(datos['version'])
PY
)
if [[ ! -f "$ESTADO/ollama.version" ]] || [[ "$(cat "$ESTADO/ollama.version")" != "${OLLAMA_DEPENDENCIA[2]}" ]]; then
  printf 'Descargando Ollama con comprobación de SHA-256.\n'
  ARCHIVO_OLLAMA="$ESTADO/descargas/ollama.tar.zst"
  curl --fail --location --retry 5 --retry-delay 3 --continue-at - "${OLLAMA_DEPENDENCIA[0]}" -o "$ARCHIVO_OLLAMA"
  if ! printf '%s  %s\n' "${OLLAMA_DEPENDENCIA[1]}" "$ARCHIVO_OLLAMA" | sha256sum --check -; then
    rm -f "$ARCHIVO_OLLAMA"
    exit 1
  fi
  tar --zstd -xf "$ARCHIVO_OLLAMA" -C /usr
  command -v ollama >/dev/null
  printf '%s' "${OLLAMA_DEPENDENCIA[2]}" > "$ESTADO/ollama.version"
  rm -f "$ARCHIVO_OLLAMA"
fi

cat > /etc/systemd/system/ciel-ollama.service <<'SERVICIO'
[Unit]
Description=Ollama privado de Agente Ciel Libre
After=docker.service
Requires=docker.service
[Service]
ExecStart=/usr/bin/ollama serve
Environment=OLLAMA_HOST=172.17.0.1:11436
Environment=OLLAMA_MODELS=/var/lib/agente-ciel/modelos
Environment=OLLAMA_NUM_PARALLEL=1
Environment=OLLAMA_MAX_LOADED_MODELS=1
Environment=OLLAMA_FLASH_ATTENTION=1
Environment=OLLAMA_KV_CACHE_TYPE=q8_0
Environment=LD_LIBRARY_PATH=/usr/lib/wsl/lib
Restart=on-failure
RestartSec=3
[Install]
WantedBy=multi-user.target
SERVICIO
systemctl daemon-reload
systemctl enable --now ciel-ollama
export OLLAMA_HOST=http://172.17.0.1:11436
for INTENTO in $(seq 1 60); do
  if curl --fail --silent "$OLLAMA_HOST/api/tags" >/dev/null; then break; fi
  sleep 2
done
curl --fail --silent "$OLLAMA_HOST/api/tags" >/dev/null
python3 preparar_modelos.py --descargas "$ESTADO/descargas"

if [[ ! -f "$ESTADO/construccion-completa" ]] || [[ "$(cat "$ESTADO/construccion-completa")" != "$(sha256sum origen.json | cut -d ' ' -f1)" ]]; then
  printf 'Construyendo la aplicación y los tres motores CAD. Esta etapa puede tardar.\n'
  docker compose --profile imagenes build
  sha256sum origen.json | cut -d ' ' -f1 > "$ESTADO/construccion-completa"
fi
# Recrear los consumidores para que lean el registro atómico recién reparado.
docker compose up -d --force-recreate api trabajador
for INTENTO in $(seq 1 90); do
  if curl --silent --fail http://127.0.0.1:8010/api/salud >/dev/null; then break; fi
  sleep 2
done
curl --silent --fail http://127.0.0.1:8010/api/salud >/dev/null
docker compose exec -T api python - <<'PY'
from aplicacion.proveedores import modelos_configurados, verificar_modelo_local
for modelo in modelos_configurados():
    verificar_modelo_local(modelo)
print('Cinco modelos locales y servicio CAD disponibles')
PY
printf 'Agente Ciel Libre está listo.\n'
