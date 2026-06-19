FROM python:3.12-slim

# Zona horaria de Guatemala por defecto (se puede cambiar en runtime con TZ).
ENV TZ=America/Guatemala

# cron para la programacion; tzdata para que la hora local sea correcta.
RUN apt-get update \
    && apt-get install -y --no-install-recommends cron tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Solo el codigo. config.json y .env se montan/proveen en runtime.
COPY monitor.py test_local.py ./
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Directorio de datos persistentes (state.json + monitor.log).
RUN mkdir -p /app/data
VOLUME ["/app/data"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
