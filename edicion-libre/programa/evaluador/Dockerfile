FROM python:3.11-slim-bookworm
WORKDIR /servicio
COPY evaluador/requirements.txt /servicio/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libxrender1 libxext6 libsm6 && rm -rf /var/lib/apt/lists/*
COPY evaluador /servicio/evaluador
ENV PYTHONPATH=/servicio PYTHONDONTWRITEBYTECODE=1
CMD ["uvicorn", "evaluador.api:aplicacion", "--host", "0.0.0.0", "--port", "8200"]
