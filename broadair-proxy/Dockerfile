# Plain Python image — the proxy is stdlib-only (no pip deps). This is NOT built
# on HA; CI builds it multi-arch and pushes to GHCR, and the add-on pulls it.
# openssl is only used to mint the self-signed cert at first start.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends openssl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY src/ ./src/
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

# Must match the module's baked-in Server Port (broadcleanair.net:8103)
EXPOSE 8103

ENTRYPOINT ["/app/entrypoint.sh"]
