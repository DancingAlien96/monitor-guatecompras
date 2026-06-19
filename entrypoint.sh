#!/bin/sh
# Entrypoint del contenedor: programa el monitor 2 veces al dia (manana y noche)
# usando cron, y deja el log en primer plano.
set -eu

APP_DIR="/app"
DATA_DIR="${DATA_DIR:-/app/data}"
LOG_FILE="$DATA_DIR/monitor.log"
STATE_FILE="$DATA_DIR/state.json"

# Horarios por defecto: 7:00 (manana) y 19:00 (noche). Formato cron, hora local.
CRON_MORNING="${CRON_MORNING:-0 7 * * *}"
CRON_NIGHT="${CRON_NIGHT:-0 19 * * *}"

mkdir -p "$DATA_DIR"
touch "$LOG_FILE"

# Aplicar zona horaria para que cron dispare a la hora local correcta.
if [ -n "${TZ:-}" ] && [ -f "/usr/share/zoneinfo/$TZ" ]; then
    ln -snf "/usr/share/zoneinfo/$TZ" /etc/localtime
    echo "$TZ" > /etc/timezone
fi

# Avisos tempranos si falta configuracion (no abortar; el correo fallara y se vera en el log).
if [ ! -f "$APP_DIR/config.json" ]; then
    echo "[entrypoint] ADVERTENCIA: no existe /app/config.json. Montalo como volumen." >&2
fi
if [ -z "${GUATECOMPRAS_SMTP_PASSWORD:-}" ] && [ ! -f "$APP_DIR/.env" ]; then
    echo "[entrypoint] ADVERTENCIA: falta GUATECOMPRAS_SMTP_PASSWORD y /app/.env; el envio de correo fallara." >&2
fi

# Comando que ejecutara cada corrida. El estado vive en el volumen para no repetir correos.
RUN_CMD="cd $APP_DIR && /usr/local/bin/python monitor.py --state $STATE_FILE >> $LOG_FILE 2>&1"

# cron de Debian NO hereda el entorno del contenedor: guardamos las variables
# relevantes (incl. la contrasena SMTP) para que cada job las cargue con 'source'.
printenv \
    | grep -E '^(GUATECOMPRAS_[A-Za-z0-9_]*|TZ)=' \
    | sed -E 's/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/export \1="\2"/' \
    > /app/container.env || true

# Generar la definicion de cron con las dos corridas diarias.
cat > /etc/cron.d/guatecompras <<EOF
SHELL=/bin/sh
PATH=/usr/local/bin:/usr/bin:/bin
$CRON_MORNING root . /app/container.env; $RUN_CMD
$CRON_NIGHT root . /app/container.env; $RUN_CMD
EOF
chmod 0644 /etc/cron.d/guatecompras

echo "[entrypoint] Zona horaria : ${TZ:-sistema}"
echo "[entrypoint] Programado    : '$CRON_MORNING' (manana) y '$CRON_NIGHT' (noche)"
echo "[entrypoint] Estado        : $STATE_FILE"
echo "[entrypoint] Log           : $LOG_FILE"

# Corrida inmediata opcional (util para probar el contenedor).
if [ "${RUN_ON_START:-false}" = "true" ]; then
    echo "[entrypoint] RUN_ON_START=true -> ejecutando una corrida inicial..."
    sh -c ". /app/container.env; $RUN_CMD" || echo "[entrypoint] La corrida inicial fallo (revisa el log)."
fi

# Iniciar el daemon de cron y seguir el log en primer plano (mantiene vivo el contenedor).
cron
exec tail -F "$LOG_FILE"
