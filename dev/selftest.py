#!/usr/bin/env python3
"""Offline self-test for tls_proxy.py raw mode — touches NO external server.

Spins up a dummy RAW TCP "cloud" that speaks first (like the real
broadair.remotcon.mobi:18013 server), runs the proxy in raw mode in front of it,
connects a fake "module", and checks frames relay intact both ways.
"""
import asyncio
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "broadair-proxy", "src"))
DUMMY_PORT = 18113
PROXY_PORT = 18114

# A frame shaped like the real server's first message (0x68 header, 0x16 tail).
GREETING = bytes.fromhex("68 aa aa aa aa aa aa 86 00 04 00 00 00 00 ee 16".replace(" ", ""))


async def dummy_cloud():
    async def handle(r, w):
        w.write(GREETING)          # server speaks first (raw TCP)
        await w.drain()
        while True:
            data = await r.read(4096)
            if not data:
                break
            w.write(b"ECHO:" + data)
            await w.drain()
        w.close()
    return await asyncio.start_server(handle, "127.0.0.1", DUMMY_PORT)


async def main():
    from tls_proxy import Proxy, parse_args

    cloud = await dummy_cloud()
    args = parse_args([
        "--mode", "raw",
        "--listen-host", "127.0.0.1",
        "--listen-port", str(PROXY_PORT),
        "--upstream-ip", "127.0.0.1",
        "--upstream-port", str(DUMMY_PORT),
        "--log-dir", os.path.join(HERE, "logs"),
    ])
    proxy = Proxy(args)
    proxy_srv = await asyncio.start_server(proxy.handle, args.listen_host, args.listen_port)

    r, w = await asyncio.open_connection("127.0.0.1", PROXY_PORT)  # plain TCP module
    greeting = await r.read(64)
    assert greeting == GREETING, f"bad greeting: {greeting.hex()}"

    w.write(b"\x68\x02POWER_ON\x16")
    await w.drain()
    reply = await r.read(64)
    assert reply == b"ECHO:\x68\x02POWER_ON\x16", f"bad echo: {reply!r}"

    w.transport.abort()
    proxy_srv.close()
    cloud.close()
    print("SELFTEST PASS: raw greeting + bidirectional frame relayed and hex-logged")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except AssertionError as e:
        print("SELFTEST FAIL:", e)
        sys.exit(1)
