#!/usr/bin/env sh
# Add-on entrypoint: read options the Supervisor wrote to /data/options.json,
# mint a self-signed cert on first boot (persisted in /data so it's stable
# across restarts), then exec the proxy. Frames print to stdout (HA Log tab)
# and are also written to /share/broadair-proxy for offline decoding.
set -e

OPTS=/data/options.json
CERT="/data/proxy.crt"
KEY="/data/proxy.key"
LOG_DIR="/share/broadair-proxy"
mkdir -p "$LOG_DIR"

# Read one option from options.json (empty string if missing / no file).
opt() { python3 -c "import json,sys;print(json.load(open('$OPTS')).get('$1',''))" 2>/dev/null || true; }

UPSTREAM_IP="$(opt upstream_ip)";   [ -n "$UPSTREAM_IP" ]   || UPSTREAM_IP="47.110.148.39"
UPSTREAM_PORT="$(opt upstream_port)"; [ -n "$UPSTREAM_PORT" ] || UPSTREAM_PORT="8103"
UPSTREAM_SNI="$(opt upstream_sni)"; [ -n "$UPSTREAM_SNI" ]   || UPSTREAM_SNI="broadcleanair.net"
VERIFY="$(opt verify_upstream)"

if [ ! -f "$CERT" ] || [ ! -f "$KEY" ]; then
  echo "[entrypoint] generating self-signed cert (CN=$UPSTREAM_SNI)"
  openssl req -x509 -newkey rsa:2048 -nodes -keyout "$KEY" -out "$CERT" -days 825 \
    -subj "/CN=$UPSTREAM_SNI" -addext "subjectAltName=DNS:$UPSTREAM_SNI"
fi

set -- --listen-host 0.0.0.0 --listen-port 8103 \
  --upstream-ip "$UPSTREAM_IP" --upstream-port "$UPSTREAM_PORT" \
  --upstream-sni "$UPSTREAM_SNI" --cert "$CERT" --key "$KEY" --log-dir "$LOG_DIR"

# options.json booleans serialize as Python True/False via our reader.
if [ "$VERIFY" = "True" ] || [ "$VERIFY" = "true" ]; then
  set -- "$@" --verify-upstream
fi

echo "[entrypoint] starting proxy -> ${UPSTREAM_IP}:${UPSTREAM_PORT} (SNI ${UPSTREAM_SNI})"
exec python3 /app/src/tls_proxy.py "$@"
