# Changelog

## 1.0.2
- **Pivot to the real module endpoint.** Recon found the module connects to
  `broadair.remotcon.mobi:18013` over **raw TCP** (not `broadcleanair.net:8103`
  TLS — that's only the REST API). Added `--mode raw` (default) and switched the
  add-on to a raw TCP relay on `:18013` → `47.110.148.39:18013`. `tls` mode kept
  as an option. Verified end-to-end against the real server.

## 1.0.0
- Initial add-on: TLS-terminating MITM proxy on `:8103`, self-signed cert minted
  on first boot, hex-logs both directions to the Log tab and
  `/share/broadair-proxy/`. Dials the real cloud by pinned IP + SNI.
