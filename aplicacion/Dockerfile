FROM node:22-alpine AS interfaz
WORKDIR /interfaz
COPY interfaz/package.json interfaz/package-lock.json ./
RUN npm ci
COPY interfaz/index.html interfaz/vite.config.js ./
COPY interfaz/src ./src
RUN npm run construir

FROM python:3.11-slim-bookworm
WORKDIR /servicio
COPY aplicacion/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY aplicacion /servicio/aplicacion
COPY datos/prompts_60_v1.json /servicio/datos/prompts_60_v1.json
COPY datos/prompts_45_v1.json /servicio/datos/prompts_45_v1.json
COPY --from=interfaz /interfaz/dist /servicio/aplicacion/estaticos
ENV PYTHONPATH=/servicio PYTHONDONTWRITEBYTECODE=1
