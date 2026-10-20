#!/usr/bin/env bash
set -Eeuo pipefail
ORIGEN="$1"
RESULTADOS="${2:?Falta la carpeta Windows de resultados}"
[[ "$(cat /etc/agente-ciel-libre)" == "ciel-libre-v1" ]] || exit 1
export DEBIAN_FRONTEND=noninteractive
if ! command -v unzip >/dev/null; then
  apt-get update
  apt-get install -y --no-install-recommends unzip ca-certificates
fi
mkdir -p /opt/agente-ciel-libre/nuevo
unzip -q -o "$ORIGEN/programa.zip" -d /opt/agente-ciel-libre/nuevo
if [[ -f /opt/agente-ciel-libre/programa/modelos_instalados.json ]]; then
  cp /opt/agente-ciel-libre/programa/modelos_instalados.json /opt/agente-ciel-libre/nuevo/modelos_instalados.json
fi
cp "$ORIGEN/dependencias.json" /opt/agente-ciel-libre/dependencias.json
cp "$ORIGEN/preparar-linux.sh" /opt/agente-ciel-libre/preparar-linux.sh
cp "$ORIGEN/abrir-linux.sh" /opt/agente-ciel-libre/abrir-linux.sh
if [[ -d /opt/agente-ciel-libre/programa ]]; then
  cp -a /opt/agente-ciel-libre/nuevo/. /opt/agente-ciel-libre/programa/
  rm -r /opt/agente-ciel-libre/nuevo
else
  mv /opt/agente-ciel-libre/nuevo /opt/agente-ciel-libre/programa
fi

mkdir -p "$RESULTADOS"
printf '%s' "$RESULTADOS" > /opt/agente-ciel-libre/ruta-resultados.txt
