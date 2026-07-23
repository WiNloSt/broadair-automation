#!/usr/bin/env python3
"""
TLS-terminating MITM proxy for the Broad "Fresh Lung" purifier.

Phase 1: the Hi-Flying WiFi module is a transparent serial<->TCP
bridge that connects out over TLS to broadcleanair.net:8103. This proxy sits in
the middle so we can read the plaintext command/status frames:

    [module] --TLS--> [this proxy] --TLS--> [broadcleanair.net:8103]
                          |
                    hex-logs both directions

The module leg is terminated with a self-signed cert (see gen_cert.sh). The
make-or-break question is whether the module validates that
cert. If it does, the handshake on the module side fails and we fall back to
UART capture; this proxy logs that failure clearly so you know which case you hit.

NOTHING here changes any server, router, or module config. Redirecting the
module's traffic to this proxy (DNS override or Server Address change) is a
separate, manual step you perform when you're ready.
"""

import argparse
import asyncio
import os
import ssl
import sys
from datetime import datetime, timezone

# --- Recon defaults (resolved 2026-07-23) ----------------------------------
# Resolve the REAL upstream IP before any DNS override exists; if you point
# broadcleanair.net at this proxy, DNS can no longer find the real server, so we
# dial its IP directly and present the hostname via SNI.
DEFAULT_UPSTREAM_IP = "47.110.148.39"
DEFAULT_UPSTREAM_SNI = "broadcleanair.net"
DEFAULT_UPSTREAM_PORT = 8103
DEFAULT_LISTEN_PORT = 8103


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + "Z"


def hexdump(data: bytes, prefix: str = "") -> str:
    """Classic offset / hex / ascii dump."""
    lines = []
    for off in range(0, len(data), 16):
        chunk = data[off:off + 16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        hex_part = f"{hex_part:<47}"  # 16*3-1 = 47 cols
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{prefix}{off:08x}  {hex_part}  |{asc}|")
    return "\n".join(lines)


class Logger:
    """Writes to stdout and (optionally) a per-connection file."""

    def __init__(self, conn_id: str, log_dir: str | None):
        self.conn_id = conn_id
        self.fh = None
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
            path = os.path.join(log_dir, f"{conn_id}.log")
            self.fh = open(path, "a", buffering=1)  # line-buffered
            self.path = path
        else:
            self.path = None

    def line(self, msg: str) -> None:
        out = f"[{ts()}] [{self.conn_id}] {msg}"
        print(out, flush=True)
        if self.fh:
            self.fh.write(out + "\n")

    def frame(self, direction: str, data: bytes) -> None:
        """direction: 'C>S' (module->cloud) or 'S>C' (cloud->module)."""
        head = f"[{ts()}] [{self.conn_id}] {direction} {len(data)} bytes"
        body = hexdump(data)
        print(head + "\n" + body, flush=True)
        if self.fh:
            self.fh.write(head + "\n" + body + "\n")

    def close(self) -> None:
        if self.fh:
            self.fh.close()


async def pump(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    direction: str,
    log: Logger,
) -> None:
    """Copy one direction, logging every chunk, until EOF."""
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
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
        # --- Downstream (module -> us): present our self-signed cert ---
        self.server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.server_ctx.load_cert_chain(args.cert, args.key)
        # --- Upstream (us -> real cloud) ---
        self.client_ctx = ssl.create_default_context()
        if not args.verify_upstream:
            # Robust default: the real cert is valid, but we dial by IP with SNI
            # and don't want a hostname/verify hiccup to break capture.
            self.client_ctx.check_hostname = False
            self.client_ctx.verify_mode = ssl.CERT_NONE

    async def handle(self, c_reader, c_writer):
        self._counter += 1
        peer = c_writer.get_extra_info("peername")
        conn_id = f"conn{self._counter:04d}_{datetime.now(timezone.utc).strftime('%H%M%S')}"
        log = Logger(conn_id, self.args.log_dir)
        log.line(f"module connected from {peer}"
                 + (f"  (logging to {log.path})" if log.path else ""))

        u_reader = u_writer = None
        try:
            u_reader, u_writer = await asyncio.wait_for(
                asyncio.open_connection(
                    self.args.upstream_ip,
                    self.args.upstream_port,
                    ssl=self.client_ctx,
                    server_hostname=self.args.upstream_sni,
                ),
                timeout=15,
            )
            log.line(f"upstream connected -> {self.args.upstream_ip}:"
                     f"{self.args.upstream_port} (SNI {self.args.upstream_sni})")
        except Exception as e:  # noqa: BLE001 - want to log any failure mode
            log.line(f"UPSTREAM CONNECT FAILED: {type(e).__name__}: {e}")
            c_writer.close()
            log.close()
            return

        await asyncio.gather(
            pump(c_reader, u_writer, "C>S", log),  # module -> cloud
            pump(u_reader, c_writer, "S>C", log),  # cloud  -> module
        )

        for w in (c_writer, u_writer):
            try:
                w.close()
            except OSError:
                pass
        log.line("connection closed")
        log.close()

    async def run(self):
        server = await asyncio.start_server(
            self.handle,
            self.args.listen_host,
            self.args.listen_port,
            ssl=self.server_ctx,
        )
        addrs = ", ".join(str(s.getsockname()) for s in server.sockets)
        print(f"[{ts()}] TLS MITM proxy listening on {addrs}", flush=True)
        print(f"[{ts()}] forwarding -> {self.args.upstream_ip}:"
              f"{self.args.upstream_port} (SNI {self.args.upstream_sni}, "
              f"verify={'on' if self.args.verify_upstream else 'off'})", flush=True)
        print(f"[{ts()}] NOTE: nothing is redirected yet. Point the module here "
              f"only when you're ready (DNS override or Server Address).", flush=True)
        async with server:
            await server.serve_forever()


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    here = os.path.dirname(os.path.abspath(__file__))
    p.add_argument("--listen-host", default=os.environ.get("PROXY_LISTEN_HOST", "0.0.0.0"))
    p.add_argument("--listen-port", type=int,
                   default=int(os.environ.get("PROXY_LISTEN_PORT", DEFAULT_LISTEN_PORT)))
    p.add_argument("--upstream-ip", default=os.environ.get("PROXY_UPSTREAM_IP", DEFAULT_UPSTREAM_IP))
    p.add_argument("--upstream-port", type=int,
                   default=int(os.environ.get("PROXY_UPSTREAM_PORT", DEFAULT_UPSTREAM_PORT)))
    p.add_argument("--upstream-sni", default=os.environ.get("PROXY_UPSTREAM_SNI", DEFAULT_UPSTREAM_SNI))
    p.add_argument("--cert", default=os.environ.get("PROXY_CERT", os.path.join(here, "certs", "proxy.crt")))
    p.add_argument("--key", default=os.environ.get("PROXY_KEY", os.path.join(here, "certs", "proxy.key")))
    p.add_argument("--log-dir", default=os.environ.get("PROXY_LOG_DIR", os.path.join(here, "logs")))
    p.add_argument("--verify-upstream", action="store_true",
                   help="verify the real broadcleanair.net cert (off by default)")
    return p.parse_args(argv)


def main():
    args = parse_args()
    if not (os.path.exists(args.cert) and os.path.exists(args.key)):
        sys.exit(f"missing cert/key ({args.cert} / {args.key}); run gen_cert.sh first")
    try:
        asyncio.run(Proxy(args).run())
    except KeyboardInterrupt:
        print(f"\n[{ts()}] shutting down", flush=True)


if __name__ == "__main__":
    main()
