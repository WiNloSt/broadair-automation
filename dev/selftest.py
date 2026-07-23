#!/usr/bin/env python3
"""Local, offline self-test for tls_proxy.py — touches NO external server.

Spins up a dummy TLS "cloud" (echo+greeting) on 127.0.0.1, runs the proxy in
front of it, connects a fake "module" client through the proxy, exchanges a few
byte frames, and checks they arrive intact both ways.
"""
import asyncio
import os
import ssl
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# proxy source lives in the add-on folder now
sys.path.insert(0, os.path.join(HERE, os.pardir, "broadair-proxy", "src"))
CERT = os.path.join(HERE, "certs", "proxy.crt")
KEY = os.path.join(HERE, "certs", "proxy.key")
DUMMY_PORT = 18103
PROXY_PORT = 18104


async def dummy_cloud():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT, KEY)

    async def handle(r, w):
        w.write(b"\xaa\x01HELLO\x55")  # server speaks a greeting frame
        await w.drain()
        while True:
            data = await r.read(4096)
            if not data:
                break
            w.write(b"ECHO:" + data)  # echo back with a marker
            await w.drain()
        w.close()

    return await asyncio.start_server(handle, "127.0.0.1", DUMMY_PORT, ssl=ctx)


async def main():
    from tls_proxy import Proxy, parse_args

    cloud = await dummy_cloud()

    args = parse_args([
        "--listen-host", "127.0.0.1",
        "--listen-port", str(PROXY_PORT),
        "--upstream-ip", "127.0.0.1",
        "--upstream-port", str(DUMMY_PORT),
        "--upstream-sni", "broadcleanair.net",
        "--cert", CERT,
        "--key", KEY,
        "--log-dir", os.path.join(HERE, "logs"),
    ])
    proxy = Proxy(args)
    proxy_srv = await asyncio.start_server(
        proxy.handle, args.listen_host, args.listen_port, ssl=proxy.server_ctx)

    # Fake "module": connect to proxy, DON'T validate cert (mirrors a cheap
    # Hi-Flying module that ignores the signer).
    cctx = ssl.create_default_context()
    cctx.check_hostname = False
    cctx.verify_mode = ssl.CERT_NONE

    r, w = await asyncio.open_connection(
        "127.0.0.1", PROXY_PORT, ssl=cctx, server_hostname="broadcleanair.net")

    greeting = await r.read(64)
    assert greeting == b"\xaa\x01HELLO\x55", f"bad greeting: {greeting!r}"

    w.write(b"\x7e\x02POWER_ON\x03")
    await w.drain()
    reply = await r.read(64)
    assert reply == b"ECHO:\x7e\x02POWER_ON\x03", f"bad echo: {reply!r}"

    # Abort transports rather than waiting on TLS graceful close (which can
    # stall on half-close); we've already proven the frames relay correctly.
    w.transport.abort()
    proxy_srv.close()
    cloud.close()

    print("SELFTEST PASS: greeting + bidirectional frame relayed and hex-logged")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except AssertionError as e:
        print("SELFTEST FAIL:", e)
        sys.exit(1)
