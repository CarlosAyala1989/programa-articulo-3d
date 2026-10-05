FROM python:3.11-slim-bookworm
RUN pip install --no-cache-dir cadquery==2.6.1
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libxrender1 libxext6 libsm6 && rm -rf /var/lib/apt/lists/*
COPY motores/ejecutar.py /motor/ejecutar.py
ENV MOTOR_CAD=cadquery
USER 10001:10001
CMD ["python", "/motor/ejecutar.py"]
