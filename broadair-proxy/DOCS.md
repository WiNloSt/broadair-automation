# Broad Air Capture Proxy

Raw TCP relay that captures the Broad "Fresh Lung" purifier's **module** traffic.

Recon finding: the Hi-Flying WiFi module's configured Server Address is
`broadair.remotcon.mobi:18013` (a **raw TCP**, non-TLS binary frame protocol —
`0x68` header … `0x16` terminator). `broadcleanair.net:8103` is only the app/HA
**REST API** and is NOT intercepted here.

```
[module] --raw TCP--> [this add-on :18013] --raw TCP--> [broadair.remotcon.mobi 47.110.148.39:18013]
                            |
                  frames -> Log tab (live) + /share/broadair-proxy (files)
```

## Install

1. **Settings → Add-ons → Add-on Store → ⋮ → Repositories** → add
   `https://github.com/WiNloSt/broadair-automation` → **Add**.
2. Open **Broad Air Capture Proxy** → **Install** → **Start**. Enable *Start on
   boot* and *Watchdog*.

## Redirect the module to the proxy

Two ways. The proxy always dials the real server by pinned IP `47.110.148.39`, so
it keeps working after either redirect.

**Option 1 — change the module's Server Address (deterministic).**
Module admin page `http://192.168.2.83/` (`admin`/`admin`) → *Other Setting* →
set **Server Address** = `<HA IP>` (e.g. `192.168.2.3`), keep **Port** = `18013`
→ Save → reboot the module. This does not depend on DNS.
Original value to restore: `broadair.remotcon.mobi` / `18013`.

**Option 2 — DNS rewrite (non-invasive, only works if the module uses your DNS).**
AdGuard → *Filters → DNS rewrites*: `broadair.remotcon.mobi` → `<HA IP>`.
Then reboot the module. If nothing connects, the module isn't using AdGuard for
DNS → use Option 1.

> Do NOT rewrite `broadcleanair.net` — that's the REST API path and rewriting it
> breaks HA's control (HA rejects the proxy's cert).

## What you'll see

After the module reconnects, the **Log** tab shows:
```
client connected from ('192.168.2.83', …)
upstream connected -> 47.110.148.39:18013
S>C 16 bytes
00000000  68 aa aa aa aa aa aa 86 00 04 00 00 00 00 ee 16  |h...............|
C>S ...
```
Drive the purifier (app/HA) and each command's frame is captured for decoding.

## Options

| option | default | notes |
|--------|---------|-------|
| `mode` | `raw` | `raw` (module endpoint) or `tls` (TLS-terminating, for the REST path) |
| `listen_port` | `18013` | must match the module's Server Port |
| `upstream_ip` | `47.110.148.39` | real server, pinned by IP |
| `upstream_port` | `18013` | |
| `upstream_sni` | `broadair.remotcon.mobi` | only used in `tls` mode |

## Logs

Live frames in the **Log** tab; persistent per-connection hex dumps in
`/share/broadair-proxy/` (browse via the Samba/SSH add-on).
