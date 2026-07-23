#!/usr/bin/env bash
# Generate a self-signed cert for the TLS MITM proxy (local only — touches no
# server). CN/SAN = broadcleanair.net so the module, if it checks the name at
# all, sees the hostname it expects. Whether it *validates* the signer is the
# open question we're testing.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/certs"
mkdir -p "$DIR"

CN="${1:-broadcleanair.net}"

openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$DIR/proxy.key" \
  -out "$DIR/proxy.crt" \
  -days 825 \
  -subj "/CN=$CN" \
  -addext "subjectAltName=DNS:$CN,DNS:*.${CN#*.},IP:127.0.0.1"

chmod 600 "$DIR/proxy.key"
echo "wrote $DIR/proxy.crt and $DIR/proxy.key (CN=$CN)"
