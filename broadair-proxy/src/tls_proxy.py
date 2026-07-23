#!/usr/bin/env python3
"""
MITM capture + local-control proxy for the Broad "Fresh Lung" purifier.

The Hi-Flying WiFi module is a transparent serial<->TCP bridge. Its real Server
Address is `broadair.remotcon.mobi:18013` (raw TCP, 0x68/0x16 framed) -- NOT
broadcleanair.net:8103 (that's only the app/HA REST API).

    [module] --raw TCP--> [this proxy] --raw TCP--> [broadair.remotcon.mobi:18013]
                              |  \
                        hex-logs   control server (:8099) — inject command
                        both dirs  frames straight to the module (local control)

Because the proxy holds the module's live connection, it can write a captured
command frame (e.g. power ON/OFF) directly to the module on demand — the module
obeys, and the cloud/app path keeps working. Command bytes are supplied via
config (they embed the device MAC), never baked into the image.

Modes: --mode raw (default, module endpoint) | tls (TLS-terminating, REST path).
"""

import argparse
import asyncio
import json
import os
import ssl
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs

# --- Recon defaults (resolved 2026-07-23) ----------------------------------
DEFAULT_MODE = "raw"
DEFAULT_UPSTREAM_IP = "47.110.148.39"            # broadair.remotcon.mobi
DEFAULT_UPSTREAM_SNI = "broadair.remotcon.mobi"  # only used in --mode tls
DEFAULT_UPSTREAM_PORT = 18013
DEFAULT_LISTEN_PORT = 18013
DEFAULT_CONTROL_PORT = 8099


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + "Z"


def hexdump(data: bytes, prefix: str = "") -> str:
    lines = []
    for off in range(0, len(data), 16):
        chunk = data[off:off + 16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        hex_part = f"{hex_part:<47}"
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{prefix}{off:08x}  {hex_part}  |{asc}|")
    return "\n".join(lines)


def parse_hex(s: str) -> bytes:
    if not s:
        return b""
    try:
        return bytes.fromhex(s.replace(" ", "").replace(":", ""))
    except ValueError:
        return b""


class Logger:
    def __init__(self, conn_id, log_dir):
        self.conn_id = conn_id
        self.fh = None
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
            self.path = os.path.join(log_dir, f"{conn_id}.log")
            self.fh = open(self.path, "a", buffering=1)
        else:
            self.path = None

    def line(self, msg):
        out = f"[{ts()}] [{self.conn_id}] {msg}"
        print(out, flush=True)
        if self.fh:
            self.fh.write(out + "\n")

    def frame(self, direction, data):
        head = f"[{ts()}] [{self.conn_id}] {direction} {len(data)} bytes"
        body = hexdump(data)
        print(head + "\n" + body, flush=True)
        if self.fh:
            self.fh.write(head + "\n" + body + "\n")

    def close(self):
        if self.fh:
            self.fh.close()


async def pump(reader, writer, direction, log, filt=None):
    """Copy one direction until EOF. `filt(direction, data)` -> log this chunk?
    (it also parses state as a side effect). Relay happens regardless."""
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            show = True
            if filt is not None:
                try:
                    show = filt(direction, data)
                except Exception:  # noqa: BLE001 - never break the relay
                    show = True
            if show:
                log.frame(direction, data)
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError, ssl.SSLError) as e:
        log.line(f"{direction} stream error: {type(e).__name__}: {e}")
    finally:
        try:
            writer.write_eof()
        except (OSError, RuntimeError):
            pass


class Proxy:
    def __init__(self, args):
        self.args = args
        self._counter = 0
        self.mode = args.mode
        self.control_port = args.control_port
        self.cmd_on = parse_hex(args.cmd_on)
        self.cmd_off = parse_hex(args.cmd_off)
        self.status_query = parse_hex(args.status_query)
        self.poll_interval = args.poll_interval
        # active module connection (writer toward the module) + write lock
        self.module_writer = None
        self.module_peer = None
        self.module_lock = asyncio.Lock()
        self.ctrl_log = Logger("control", args.log_dir)
        # parsed device state (from the 93-byte status dump)
        self.state = {"power_on": None, "updated": None, "raw": None}

        self.server_ctx = None
        self.client_ctx = None
        if self.mode == "tls":
            self.server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self.server_ctx.load_cert_chain(args.cert, args.key)
            self.client_ctx = ssl.create_default_context()
            if not args.verify_upstream:
                self.client_ctx.check_hostname = False
                self.client_ctx.verify_mode = ssl.CERT_NONE

    # ---- relay --------------------------------------------------------------
    async def handle(self, c_reader, c_writer):
        self._counter += 1
        peer = c_writer.get_extra_info("peername")
        conn_id = f"conn{self._counter:04d}_{datetime.now(timezone.utc).strftime('%H%M%S')}"
        log = Logger(conn_id, self.args.log_dir)
        log.line(f"client connected from {peer}"
                 + (f"  (logging to {log.path})" if log.path else ""))

        # This connection becomes the injection target (module is the only
        # persistent client; latest wins).
        self.module_writer = c_writer
        self.module_peer = peer

        try:
            u_reader, u_writer = await asyncio.wait_for(
                asyncio.open_connection(
                    self.args.upstream_ip, self.args.upstream_port,
                    ssl=self.client_ctx,
                    server_hostname=self.args.upstream_sni if self.client_ctx else None,
                ), timeout=15)
            log.line(f"upstream connected -> {self.args.upstream_ip}:{self.args.upstream_port}")
        except Exception as e:  # noqa: BLE001
            log.line(f"UPSTREAM CONNECT FAILED: {type(e).__name__}: {e}")
            c_writer.close(); log.close(); return

        await asyncio.gather(
            pump(c_reader, u_writer, "C>S", log, filt=self._filter),
            pump(u_reader, c_writer, "S>C", log, filt=self._filter),
        )

        for w in (c_writer, u_writer):
            try:
                w.close()
            except OSError:
                pass
        if self.module_writer is c_writer:
            self.module_writer = None
            self.module_peer = None
        log.line("connection closed")
        log.close()

    # ---- frame filtering + status parsing -----------------------------------
    def _filter(self, direction, data):
        """Parse state (side effect); return True if this chunk should be logged.
        Routine polls/heartbeats/status frames are suppressed to keep the log
        focused on real commands even when polling fast."""
        self._parse_status(data)
        return not self._is_routine(data)

    @staticmethod
    def _is_routine(d):
        # 68 | addr[6] | 86 | ctrl(8) | len(9) | ...
        if len(d) < 10 or d[0] != 0x68 or d[7] != 0x86:
            return False
        ctrl, ln = d[8], d[9]
        # 00=server poll, (80,0b)=heartbeat, (82,51)=status dump, (02,0c)=status query
        return ctrl == 0x00 or (ctrl, ln) in {(0x80, 0x0b), (0x82, 0x51), (0x02, 0x0c)}

    def _parse_status(self, data: bytes):
        """Extract device state from a 93-byte status dump (control 86 82 51).
        byte 18 (relative to the 0x68 frame start) = power: 01=on, 00=off."""
        idx = data.find(b"\x86\x82\x51")   # 86 at frame offset 7 -> byte18 = idx+11
        if idx < 0 or idx + 11 >= len(data):
            return
        frame_start = idx - 7
        power = data[idx + 11]
        prev = self.state.get("power_on")
        self.state = {
            "power_on": bool(power),
            "power_raw": power,
            "updated": ts(),
            "raw": data[frame_start:frame_start + 93].hex(),
        }
        if prev is not None and prev != bool(power):
            print(f"[{ts()}] [state] power {'on' if prev else 'off'} -> "
                  f"{'on' if power else 'off'}", flush=True)

    # ---- periodic status poll ----------------------------------------------
    async def poller(self):
        if not self.status_query or self.poll_interval <= 0:
            return
        while True:
            await asyncio.sleep(self.poll_interval)
            w = self.module_writer
            if w is not None and not w.is_closing():
                try:
                    async with self.module_lock:
                        w.write(self.status_query)
                        await w.drain()
                except OSError:
                    pass

    # ---- injection ----------------------------------------------------------
    async def inject(self, frame: bytes):
        if not frame:
            return False, "empty/invalid frame"
        w = self.module_writer
        if w is None or w.is_closing():
            return False, "module not connected"
        async with self.module_lock:
            w.write(frame)
            await w.drain()
        self.ctrl_log.frame(f"INJECT->module {self.module_peer}", frame)
        return True, f"sent {len(frame)} bytes to {self.module_peer}"

    # ---- control HTTP server ------------------------------------------------
    async def handle_control(self, reader, writer):
        try:
            req = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError):
            writer.close(); return
        line = req.split(b"\r\n", 1)[0].decode("latin1", "replace")
        parts = line.split()
        raw_path = parts[1] if len(parts) >= 2 else "/"
        u = urlparse(raw_path)
        q = parse_qs(u.query)
        status, payload = "200 OK", {}

        if u.path == "/status":
            payload = {"module_connected": self.module_writer is not None
                       and not self.module_writer.is_closing(),
                       "peer": str(self.module_peer),
                       "have_cmd_on": bool(self.cmd_on),
                       "have_cmd_off": bool(self.cmd_off),
                       "power_on": self.state["power_on"],
                       "state_updated": self.state["updated"],
                       "raw": self.state.get("raw")}
        elif u.path in ("/on", "/off"):
            frame = self.cmd_on if u.path == "/on" else self.cmd_off
            if not frame:
                status, payload = "400 Bad Request", {"ok": False, "detail": f"cmd_{u.path[1:]} not configured"}
            else:
                ok, msg = await self.inject(frame)
                payload = {"ok": ok, "action": u.path[1:], "detail": msg}
        elif u.path == "/inject":
            frame = parse_hex(q.get("hex", [""])[0])
            if not frame:
                status, payload = "400 Bad Request", {"ok": False, "detail": "bad or missing ?hex="}
            else:
                ok, msg = await self.inject(frame)
                payload = {"ok": ok, "detail": msg}
        else:
            status, payload = "404 Not Found", {"ok": False, "detail": "paths: /status /on /off /inject?hex="}

        body = json.dumps(payload)
        resp = (f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n{body}")
        writer.write(resp.encode())
        try:
            await writer.drain()
        except OSError:
            pass
        writer.close()

    # ---- run both servers ---------------------------------------------------
    async def run(self):
        relay = await asyncio.start_server(
            self.handle, self.args.listen_host, self.args.listen_port, ssl=self.server_ctx)
        control = await asyncio.start_server(
            self.handle_control, self.args.listen_host, self.control_port)
        kind = "TLS-terminating MITM" if self.mode == "tls" else "raw TCP relay"
        addrs = ", ".join(str(s.getsockname()) for s in relay.sockets)
        print(f"[{ts()}] {kind} listening on {addrs}", flush=True)
        print(f"[{ts()}] forwarding -> {self.args.upstream_ip}:{self.args.upstream_port} (mode={self.mode})", flush=True)
        print(f"[{ts()}] control server on :{self.control_port} "
              f"(/status /on /off /inject?hex=)  cmd_on={'set' if self.cmd_on else 'unset'} "
              f"cmd_off={'set' if self.cmd_off else 'unset'} "
              f"poll={self.poll_interval if self.status_query else 'off'}s", flush=True)
        asyncio.create_task(self.poller())
        async with relay, control:
            await asyncio.gather(relay.serve_forever(), control.serve_forever())


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    here = os.path.dirname(os.path.abspath(__file__))
    env = os.environ.get
    p.add_argument("--mode", choices=["raw", "tls"], default=env("PROXY_MODE", DEFAULT_MODE))
    p.add_argument("--listen-host", default=env("PROXY_LISTEN_HOST", "0.0.0.0"))
    p.add_argument("--listen-port", type=int, default=int(env("PROXY_LISTEN_PORT", DEFAULT_LISTEN_PORT)))
    p.add_argument("--control-port", type=int, default=int(env("PROXY_CONTROL_PORT", DEFAULT_CONTROL_PORT)))
    p.add_argument("--upstream-ip", default=env("PROXY_UPSTREAM_IP", DEFAULT_UPSTREAM_IP))
    p.add_argument("--upstream-port", type=int, default=int(env("PROXY_UPSTREAM_PORT", DEFAULT_UPSTREAM_PORT)))
    p.add_argument("--upstream-sni", default=env("PROXY_UPSTREAM_SNI", DEFAULT_UPSTREAM_SNI))
    p.add_argument("--cmd-on", default=env("PROXY_CMD_ON", ""), help="hex frame for power ON")
    p.add_argument("--cmd-off", default=env("PROXY_CMD_OFF", ""), help="hex frame for power OFF")
    p.add_argument("--status-query", default=env("PROXY_STATUS_QUERY", ""),
                   help="hex frame that asks the device for a status dump")
    p.add_argument("--poll-interval", type=int, default=int(env("PROXY_POLL_INTERVAL", "30")),
                   help="seconds between status polls (0 disables)")
    p.add_argument("--cert", default=env("PROXY_CERT", os.path.join(here, "certs", "proxy.crt")))
    p.add_argument("--key", default=env("PROXY_KEY", os.path.join(here, "certs", "proxy.key")))
    p.add_argument("--log-dir", default=env("PROXY_LOG_DIR", os.path.join(here, "logs")))
    p.add_argument("--verify-upstream", action="store_true")
    return p.parse_args(argv)


def main():
    args = parse_args()
    if args.mode == "tls" and not (os.path.exists(args.cert) and os.path.exists(args.key)):
        sys.exit(f"tls mode needs cert/key ({args.cert} / {args.key})")
    try:
        asyncio.run(Proxy(args).run())
    except KeyboardInterrupt:
        print(f"\n[{ts()}] shutting down", flush=True)


if __name__ == "__main__":
    main()
