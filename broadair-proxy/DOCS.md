# Broad Air TLS Proxy

TLS-terminating MITM proxy for the Broad "Fresh Lung" purifier. It sits between
the Hi-Flying WiFi module and the Broad cloud so you can read the plaintext
command/status frames:

```
[module] --TLS--> [this add-on :8103] --TLS--> [broadcleanair.net 47.110.148.39:8103]
                        |
              frames -> Log tab (live) + /share/broadair-proxy (files)
```

## Install

1. **Settings → Add-ons → Add-on Store → ⋮ → Repositories** → add
   `https://github.com/WiNloSt/broadair-automation` → **Add**.
2. Open **Broad Air TLS Proxy** in the store → **Install** → **Start**.
   - The GHCR image must be **public** (Package settings → Change visibility →
     Public) or HA can't pull it. One-time step after the first CI build.

## It does NOT touch the module or any server

Running this changes nothing on your network. To actually route the module's
traffic through it you add a **DNS rewrite** (below) — a separate, reversible
step you do when ready.

## Redirect the module (AdGuard DNS rewrite)

AdGuard Home → **Filters → DNS rewrites → Add**:

| Domain | Answer |
|--------|--------|
| `broadcleanair.net` | `<your HA IP>` |

Then power-cycle the purifier so the module re-resolves. The proxy still reaches
the real cloud because it dials the pinned IP `47.110.148.39` (not the name), so
the rewrite can never loop back on it.

## The make-or-break moment

Watch the **Log** tab after the first module connection:

- `module connected` → `upstream connected` → **frames flow** = the module does
  not validate our self-signed cert. MITM works — capture every command.
- `module connected` then a TLS error with **no frames** = the module validates
  the cert (pinning). TLS is opaque → fall back to **UART capture**.

## Options

| option | default | notes |
|--------|---------|-------|
| `upstream_ip` | `47.110.148.39` | real cloud IP, resolved 2026-07-23 before any override |
| `upstream_port` | `8103` | |
| `upstream_sni` | `broadcleanair.net` | SNI presented to the real cloud |
| `verify_upstream` | `false` | verify the real cert (we dial by IP, so off) |

Listener is fixed at `0.0.0.0:8103` to match the module's baked-in Server Port.

## Logs

Live frames appear in the **Log** tab. Persistent per-connection hex dumps are
written to `/share/broadair-proxy/` (browse via the Samba/SSH add-on).
