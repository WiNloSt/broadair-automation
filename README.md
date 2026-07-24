# broadair-automation

Local control for the Broad "Fresh Lung" air purifier, without the vendor cloud.

The purifier's WiFi module (a Hi-Flying serial-to-TCP bridge) connects to
`broadair.remotcon.mobi:18013` over plain TCP and relays a binary frame protocol.
Point the module at a local proxy instead and you can read its state and send
commands directly. The proxy still forwards to the real server, so the vendor app
keeps working.

## Layout

- `broadair-proxy/` — Home Assistant add-on. A raw TCP relay the module connects
  to; it forwards to the real server, parses status, and exposes an HTTP control
  API on `:8099`. CI builds a multi-arch image and pushes it to GHCR.
- `custom_components/broadair/` — HA integration (installable via HACS). Talks to
  the add-on's API and exposes a fan entity plus sensors.
- `dev/` — offline test tools.

## How it works

```
purifier module ──TCP :18013──▶ add-on (on HA) ──TCP──▶ broadair.remotcon.mobi:18013
                                    │
                         HTTP :8099 │ ◀── integration (fan, sensors)
```

The add-on holds the module's connection independently of HA Core, so restarting
or updating HA doesn't drop the purifier's cloud link.

## Install

1. **Add-on** — Settings → Add-ons → Add-on Store → ⋮ → Repositories → add this
   repo → install **Broad Air Capture Proxy** → start. It auto-learns the device
   address from traffic; `cmd_on`/`cmd_off` options are optional seed frames.
2. **Redirect the module** — open the module admin page (`http://<module-ip>/`,
   default `admin`/`admin`) → Other Setting → set **Server Address** to your HA
   IP, keep **Port** `18013`, save. The module reconnects through the add-on.
   Reversible: original address is `broadair.remotcon.mobi`. DNS rewrites don't
   work here — they also catch the phone app and break its login.
3. **Integration** — HACS → custom repository → this repo (type: Integration) →
   install → Settings → Devices & Services → Add → Broad Air Purifier →
   host = your HA IP (or the add-on hostname), port `8099`.

## Add-on control API (`:8099`)

- `GET /status` → JSON: `power_on`, `fan_m3h`, `temp_c`, `state_updated`, `raw`
- `GET /power?on=1|0`
- `GET /fan?level=0..3` (0 sleep, 3 max)
- `GET /auto`
- `GET /cmd?b17=&b22=` — arbitrary synthesized command
- `GET /inject?hex=…` — raw frame

Options: `poll_interval` (status-poll seconds; the vendor cloud only polls the
device while the app is open, so the add-on polls it to keep state fresh),
`upstream_ip`/`upstream_port`, `mode` (`raw`|`tls`).

## Protocol

Frame: `68 | addr[6] | 86 | ctrl | len | data | sum | 16` (DL/T-645 style).
`addr` is the module MAC in reverse byte order. `sum` = bytes from `68` through
end of `data`, mod 256.

Commands (server→module, 27 bytes). Inner payload `01 10 00 <b17> 00 01 02 00 <b22>`,
followed by CRC16/Modbus of that payload, then the outer `sum`, then `16`:

| function | b17 | b22 |
|----------|-----|-----|
| power    | 00  | 1 on / 0 off |
| fan      | 01  | 0 sleep (50 m³/h) · 1 (80) · 2 (120) · 3 (180, max) |
| auto     | 0f  | 01 |

Status dump (device→server, 93 bytes, ctrl `82 51`):

| field | offset | notes |
|-------|--------|-------|
| power | byte 18 | 1 / 0 |
| airflow | byte 58 | m³/h |
| temperature | bytes 87–88 | value ÷ 10, °C |
| PM2.5 | — | not yet located (needs a changing reading to pin) |
| filter life | — | candidate byte 39, unconfirmed |

## Dev

```
cd dev && ./gen_cert.sh && python3 selftest.py   # offline relay test
```

Add-on is stdlib-only Python. CI auto-bumps the add-on version on push and builds
aarch64/amd64/armv7 images.
