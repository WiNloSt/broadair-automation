# broadair-automation

Local control for the Broad "Fresh Lung" air purifier, without the vendor cloud.

The purifier's WiFi module (a Hi-Flying serial-to-TCP bridge) connects to
`broadair.remotcon.mobi:18013` over plain TCP and relays a binary frame protocol.
Point the module at a local proxy instead and you can read its state and send
commands directly. The proxy still forwards to the real server, so the vendor app
keeps working.

## Layout

- `broadair-proxy/` — Home Assistant add-on. A raw TCP relay the module connects
  to; it forwards to the real server, parses status, synthesizes commands, and
  exposes an HTTP control API on `:8099`. CI builds a multi-arch image to GHCR.
- `custom_components/broadair/` — HA integration (installable via HACS). Talks to
  the add-on's API and exposes a fan entity plus sensors.
- `dev/` — offline test tools.

## How it works

```
purifier module ──TCP :18013──▶ add-on (on HA) ──TCP──▶ broadair.remotcon.mobi:18013
                                    │
                         HTTP :8099 │ ◀── integration (fan, sensors)
```

The module is the TCP client — it "phones home" to whatever Server Address it's
set to, so pointing it at the HA IP is all that's needed (the add-on never dials
the purifier). The add-on holds that connection independently of HA Core, so
restarting HA doesn't drop the purifier's cloud link.

## Install

1. **Add-on** — Settings → Add-ons → Add-on Store → ⋮ → Repositories → add this
   repo → install **Broad Air Capture Proxy** → start. It auto-learns the device
   address from traffic.
2. **Redirect the module** — open the module admin page (`http://<module-ip>/`,
   default `admin` / `admin`) → Other Setting → set **Server Address** to your HA
   IP, keep **Port** `18013`, save. See the redirect note below for durability.
3. **Integration** — HACS → custom repository → this repo (type: Integration) →
   install → Settings → Devices & Services → Add → Broad Air Purifier →
   host = your HA IP (or the add-on hostname), port `8099`.

Entities: a **fan** (power, speed Sleep/1/2/3, presets Auto and Normal) plus
**PM2.5**, **temperature**, and **airflow** sensors. Changes made from the app or
physical remote are reflected too.

## Add-on control API (`:8099`)

- `GET /status` → JSON: `power_on`, `fan_m3h`, `auto`, `pm25`, `temp_c`, `raw`
- `GET /power?on=1|0`
- `GET /fan?level=0..3` (0 sleep, 3 max)
- `GET /auto` (does not power on by itself)
- `GET /cmd?b17=&b22=` — arbitrary synthesized command
- `GET /inject?hex=…` — raw frame

After each command the add-on re-queries the device, so `/status` (and HA) reflect
the change within about a second. Options: `poll_interval`, `upstream_ip`/
`upstream_port`, `mode` (`raw`|`tls`).

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

Status dump (device→server, 93 bytes, ctrl `82 51`). Offsets from the `68`:

| field | offset | notes |
|-------|--------|-------|
| power | 18 | 1 / 0 |
| auto mode | 48 | 1 auto / 0 manual |
| airflow | 58 | m³/h |
| PM2.5 | 69–70 | 16-bit, µg/m³ |
| temperature | 87–88 | ÷ 10, °C |
| filter totals | 23–24, 25–26 | HEPA 3000 h, coarse 720 h (16-bit) |
| filter remaining | — | undecoded; a timer reset didn't change the frame |

## Notes / findings

- **Redirect durability.** The Server-Address change only affects the module (not
  the phone), but the vendor cloud can push a config sync that reverts it back to
  `broadair.remotcon.mobi` — observed right after resetting a filter in the app.
  For a permanent redirect use a **router DNAT/firewall rule** (module IP → the HA
  IP, port 18013); the cloud can't undo that, and the phone stays unaffected.
- **Not DNS.** A DNS rewrite of `broadair.remotcon.mobi` also redirects the module,
  but it catches the phone app too and breaks its login. Avoid it.
- **Cloud polling.** The cloud only queries the device for fresh state while the app
  is open (every few seconds), and stops when idle — so the add-on polls the device
  itself (`poll_interval`) to keep HA state current.
- **Command feedback.** The add-on both re-queries after a command and sniffs the
  cloud's own commands as they pass through, so app/remote changes show up without
  waiting for a poll.

## Dev

```
cd dev && ./gen_cert.sh && python3 selftest.py   # offline relay test
```

Add-on is stdlib-only Python. CI auto-bumps the add-on version on push and builds
aarch64/amd64/armv7 images.
