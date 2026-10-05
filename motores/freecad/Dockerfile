FROM debian:bookworm-slim
ENV DEBIAN_FRONTEND=noninteractive QT_QPA_PLATFORM=offscreen
RUN apt-get update && apt-get install -y --no-install-recommends python3 freecad-python3 && rm -rf /var/lib/apt/lists/*
RUN printf 'ciel:x:10001:10001::/tmp:/usr/sbin/nologin\n' >> /etc/passwd && printf 'ciel:x:10001:\n' >> /etc/group
COPY motores/ejecutar.py /motor/ejecutar.py
ENV MOTOR_CAD=freecad PYTHONPATH=/usr/lib/freecad-python3/lib:/usr/lib/freecad/lib
USER 10001:10001
CMD ["/usr/bin/python3", "/motor/ejecutar.py"]
