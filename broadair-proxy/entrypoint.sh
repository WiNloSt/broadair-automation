#!/usr/bin/env sh
# Add-on entrypoint: read options from /data/options.json and run the proxy.
# Default is RAW TCP relay for the module endpoint (broadair.remotcon.mobi:18013)
# plus a local-control HTTP API on :8099. Frames print to stdout (HA Log tab)
# and are written to /share/broadair-proxy.
set -e

OPTS=/data/options.json
LOG_DIR="/share/broadair-proxy"
mkdir -p "$LOG_DIR"

opt() { python3 -c "import json,sys;print(json.load(open('$OPTS')).get('$1',''))" 2>/dev/null || true; }

MODE="$(opt mode)";                   [ -n "$MODE" ]          || MODE="raw"
LISTEN_PORT="$(opt listen_port)";     [ -n "$LISTEN_PORT" ]   || LISTEN_PORT="18013"
CONTROL_PORT="$(opt control_port)";   [ -n "$CONTROL_PORT" ]  || CONTROL_PORT="8099"
UPSTREAM_IP="$(opt upstream_ip)";     [ -n "$UPSTREAM_IP" ]   || UPSTREAM_IP="47.110.148.39"
UPSTREAM_PORT="$(opt upstream_port)"; [ -n "$UPSTREAM_PORT" ] || UPSTREAM_PORT="18013"
CMD_ON="$(opt cmd_on)"
CMD_OFF="$(opt cmd_off)"

set -- --mode "$MODE" --listen-host 0.0.0.0 --listen-port "$LISTEN_PORT" \
  --control-port "$CONTROL_PORT" \
  --upstream-ip "$UPSTREAM_IP" --upstream-port "$UPSTREAM_PORT" --log-dir "$LOG_DIR" \
  --cmd-on "$CMD_ON" --cmd-off "$CMD_OFF"

# tls mode (optional): mint a self-signed cert on first boot.
if [ "$MODE" = "tls" ]; then
  CERT="/data/proxy.crt"; KEY="/data/proxy.key"
  SNI="$(opt upstream_sni)"; [ -n "$SNI" ] || SNI="broadair.remotcon.mobi"
  if [ ! -f "$CERT" ] || [ ! -f "$KEY" ]; then
    echo "[entrypoint] generating self-signed cert (CN=$SNI)"
    openssl req -x509 -newkey rsa:2048 -nodes -keyout "$KEY" -out "$CERT" -days 825 \
      -subj "/CN=$SNI" -addext "subjectAltName=DNS:$SNI"
  fi
  set -- "$@" --cert "$CERT" --key "$KEY" --upstream-sni "$SNI"
fi

echo "[entrypoint] mode=$MODE relay=:$LISTEN_PORT control=:$CONTROL_PORT upstream=${UPSTREAM_IP}:${UPSTREAM_PORT}"
exec python3 /app/src/tls_proxy.py "$@"
