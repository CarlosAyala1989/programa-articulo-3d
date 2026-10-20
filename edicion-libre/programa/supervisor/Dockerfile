FROM python:3.11-slim-bookworm
WORKDIR /servicio
COPY supervisor/requirements.txt /servicio/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY supervisor /servicio/supervisor
CMD ["uvicorn", "supervisor.api:aplicacion", "--host", "0.0.0.0", "--port", "8100"]
