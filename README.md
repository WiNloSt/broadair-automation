# broadair-automation

Local control for the Broad "Fresh Lung" air purifier, without depending on the
`broadcleanair.net` cloud.

This repo is a **Home Assistant add-on repository**. The `broadair-proxy` add-on
is a raw TCP relay that captures the purifier module's serial frames
(`broadair.remotcon.mobi:18013`) so the protocol can be decoded and replayed
locally.

## Layout

```
broadair-automation/
  repository.yaml                  makes this an HA add-on repository
  broadair-proxy/                  the add-on
    config.yaml                    manifest (image, version, options, ports)
    Dockerfile                     stdlib-only Python image
    entrypoint.sh                  mints cert, reads options, runs proxy
    src/tls_proxy.py               the proxy
    DOCS.md / CHANGELOG.md
  .github/workflows/               CI: auto-bump version + build/push GHCR image
  dev/                             offline test tools (not shipped in the image)
    selftest.py  gen_cert.sh
```

## The workflow you asked for

1. **Code** — edit `broadair-proxy/`.
2. **Commit & push** to `main` — CI **auto-bumps the patch version**, then builds
   a **multi-arch image** (aarch64/amd64/armv7) and pushes it to GHCR tagged with
   that version.
3. **Update on HA** — the Add-on Store shows an **Update** button (hit
   ⋮ → Reload to see it immediately, or flip on **Auto-update** to do nothing).

### One-time HA setup

- Add-on Store → ⋮ → **Repositories** → add this repo's URL → **Install** the add-on.
- After the first CI build, make the GHCR package **public** (or give HA registry
  creds) so HA can pull it.

## Safety

Running the add-on changes nothing on your network. Routing the module through it
is a separate, reversible **AdGuard DNS rewrite** (`broadcleanair.net` → HA IP);
see [broadair-proxy/DOCS.md](broadair-proxy/DOCS.md). The proxy dials the real
cloud by pinned IP, so the rewrite can never loop back on it.

## Dev

```bash
cd dev && ./gen_cert.sh && python3 selftest.py   # offline, touches nothing external
```
