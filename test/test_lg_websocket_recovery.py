#!/usr/bin/env python3
"""
LG webOS stale WebSocket / recovery diagnostic.

Scenario:
1. Connect normally to the LG TV with aiowebostv.
2. KEEP the connection open.
3. Manually disable the PC Wi-Fi for ~60 seconds.
4. Re-enable Wi-Fi.
5. The script probes TCP 3000/3001 and repeatedly creates a FRESH
   WebOsClient, logging the exact stage where reconnection fails.
6. If needed, power-cycle the TV WITHOUT restarting this script.
   If the next attempt succeeds immediately, the log will make that visible.

Important:
- The script intentionally does NOT call disconnect() before the Wi-Fi cut.
- This simulates an abrupt disappearance of the client, similar to a device
  going to sleep before a WebSocket/TCP close is delivered to the TV.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import socket
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable, TypeVar

from aiowebostv import WebOsClient

LOG = logging.getLogger("lg_ws_diag")
T = TypeVar("T")

RETRY_INTERVAL = 5.0
PROBE_TIMEOUT = 2.0
INITIAL_LOSS_POLL_INTERVAL = 0.5


def elapsed(start: float) -> str:
    return f"{time.monotonic() - start:.3f}s"


async def run_stage(name: str, func: Callable[[], Awaitable[T]]) -> T:
    start = time.monotonic()
    LOG.info("STAGE START | %s", name)
    try:
        result = await func()
    except Exception as exc:
        LOG.error(
            "STAGE FAIL  | %-28s | after %s | %s: %r",
            name,
            elapsed(start),
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        raise
    LOG.info("STAGE OK    | %-28s | %s", name, elapsed(start))
    return result


class DiagnosticWebOsClient(WebOsClient):
    """WebOsClient with detailed connection-stage logging."""

    async def _create_main_ws(self):
        return await run_stage("MAIN websocket", super()._create_main_ws)

    async def _get_hello_info(self, ws):
        return await run_stage(
            "MAIN hello",
            lambda: super(DiagnosticWebOsClient, self)._get_hello_info(ws),
        )

    async def _get_pre_reg_system_info(self, ws):
        return await run_stage(
            "pre-registration system info",
            lambda: super(DiagnosticWebOsClient, self)._get_pre_reg_system_info(ws),
        )

    async def _check_registration(self, ws):
        return await run_stage(
            "SSAP registration",
            lambda: super(DiagnosticWebOsClient, self)._check_registration(ws),
        )

    async def _create_input_ws(self):
        return await run_stage("INPUT websocket", super()._create_input_ws)

    async def _get_states_and_subscribe_state_updates(self):
        return await run_stage(
            "initial states/subscriptions",
            super()._get_states_and_subscribe_state_updates,
        )

    async def _closeout_tasks(self, main_ws, input_ws):
        LOG.info(
            "CLOSEOUT      | main=%s input=%s",
            ws_state(main_ws),
            ws_state(input_ws),
        )
        start = time.monotonic()
        try:
            return await super()._closeout_tasks(main_ws, input_ws)
        finally:
            LOG.info("CLOSEOUT DONE | %s", elapsed(start))


def ws_state(ws) -> str:
    if ws is None:
        return "none"
    try:
        return (
            f"closed={ws.closed}, close_code={ws.close_code}, "
            f"exception={ws.exception()!r}"
        )
    except Exception as exc:
        return f"state-error={exc!r}"


async def tcp_probe(host: str, port: int, timeout: float = PROBE_TIMEOUT) -> bool:
    """Check whether a TCP connection can be established."""
    start = time.monotonic()
    writer = None
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        LOG.info("TCP OK        | %s:%d | %s", host, port, elapsed(start))
        return True
    except Exception as exc:
        LOG.warning(
            "TCP FAIL      | %s:%d | %s | %s: %r",
            host,
            port,
            elapsed(start),
            type(exc).__name__,
            exc,
        )
        return False
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass


async def connect_fresh(
    host: str,
    client_key: str | None,
    label: str,
    connect_timeout: float,
) -> DiagnosticWebOsClient | None:
    """Create a new aiowebostv client and attempt a full connection."""
    LOG.info("=" * 78)
    LOG.info("%s | creating FRESH WebOsClient", label)
    start = time.monotonic()

    client = DiagnosticWebOsClient(
        host=host,
        client_key=client_key,
        connect_timeout=connect_timeout,
    )

    try:
        result = await client.connect()
        LOG.info(
            "%s | FULL CONNECT SUCCESS | result=%r | total=%s",
            label,
            result,
            elapsed(start),
        )
        LOG.info("%s | main=%s", label, ws_state(client.connection))
        LOG.info("%s | input=%s", label, ws_state(client.input_connection))
        LOG.info("%s | client_key=%s", label, client.client_key)
        return client
    except Exception as exc:
        LOG.error(
            "%s | FULL CONNECT FAILED | total=%s | %s: %r",
            label,
            elapsed(start),
            type(exc).__name__,
            exc,
        )
        try:
            await client.disconnect()
        except Exception as close_exc:
            LOG.warning("%s | cleanup failed: %r", label, close_exc)
        return None


async def wait_for_initial_connection_loss(client: DiagnosticWebOsClient) -> None:
    """Wait until the initially connected client is no longer connected."""
    LOG.info("")
    LOG.info("TEST READY")
    LOG.info("1) Disable this PC's Wi-Fi now.")
    LOG.info("2) Keep Wi-Fi disabled for about 60 seconds.")
    LOG.info("3) Re-enable Wi-Fi.")
    LOG.info("4) Do NOT restart this script.")
    LOG.info("5) If reconnection keeps failing, power-cycle ONLY the TV.")
    LOG.info("")

    last_main_state = None
    last_input_state = None

    while client.is_connected():
        main_state = ws_state(client.connection)
        input_state = ws_state(client.input_connection)

        if main_state != last_main_state or input_state != last_input_state:
            LOG.info("INITIAL LIVE  | main=%s", main_state)
            LOG.info("INITIAL LIVE  | input=%s", input_state)
            last_main_state = main_state
            last_input_state = input_state

        await asyncio.sleep(INITIAL_LOSS_POLL_INTERVAL)

    LOG.warning("INITIAL CONNECTION LOST")
    LOG.warning("INITIAL AFTER LOSS | main=%s", ws_state(client.connection))
    LOG.warning("INITIAL AFTER LOSS | input=%s", ws_state(client.input_connection))


async def recovery_loop(
    host: str,
    client_key: str,
    connect_timeout: float,
) -> DiagnosticWebOsClient:
    """Retry fresh connections forever until one succeeds."""
    attempt = 0

    while True:
        attempt += 1
        LOG.info("")
        LOG.info("RECOVERY ATTEMPT #%d", attempt)

        tcp_3000 = await tcp_probe(host, 3000)
        tcp_3001 = await tcp_probe(host, 3001)

        if not tcp_3000 and not tcp_3001:
            LOG.warning(
                "TV network service not reachable yet; no aiowebostv attempt this cycle"
            )
            await asyncio.sleep(RETRY_INTERVAL)
            continue

        client = await connect_fresh(
            host,
            client_key,
            label=f"RECOVERY #{attempt}",
            connect_timeout=connect_timeout,
        )
        if client is not None:
            LOG.info("")
            LOG.info("RECOVERY CONFIRMED")
            LOG.info(
                "A completely fresh WebOsClient connected successfully after the outage."
            )
            return client

        LOG.warning(
            "Fresh client failed although TCP probe result was 3000=%s 3001=%s",
            tcp_3000,
            tcp_3001,
        )
        LOG.warning(
            "If this persists while other LAN devices work, power-cycle ONLY the TV "
            "and leave this script running."
        )
        await asyncio.sleep(RETRY_INTERVAL)


def setup_logging(log_path: Path, verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03d | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    logging.getLogger("aiowebostv").setLevel(logging.DEBUG)


async def async_main(args: argparse.Namespace) -> int:
    LOG.info("LG webOS WebSocket recovery diagnostic")
    LOG.info("Host: %s", args.host)
    LOG.info("Python: %s", sys.version.replace("\n", " "))
    LOG.info("Platform: %s", sys.platform)
    LOG.info("Connect timeout: %.1fs", args.connect_timeout)
    LOG.info("Local hostname: %s", socket.gethostname())

    initial = await connect_fresh(
        args.host,
        args.client_key,
        label="INITIAL",
        connect_timeout=args.connect_timeout,
    )
    if initial is None:
        LOG.error(
            "Initial connection failed. The TV must be reachable before starting "
            "the Wi-Fi-loss test."
        )
        return 2

    if not initial.client_key:
        LOG.error("No client key was obtained after pairing.")
        await initial.disconnect()
        return 3

    client_key = initial.client_key
    LOG.info("PAIRING KEY   | %s", client_key)

    # Critical: no disconnect before the Wi-Fi cut.
    await wait_for_initial_connection_loss(initial)

    recovered = await recovery_loop(host=args.host, client_key=client_key, connect_timeout=args.connect_timeout)

    LOG.info("")
    LOG.info("Keeping recovered connection alive for 15 seconds...")
    await asyncio.sleep(15)

    LOG.info("Recovered session still connected: %s", recovered.is_connected())
    LOG.info("Recovered MAIN : %s", ws_state(recovered.connection))
    LOG.info("Recovered INPUT: %s", ws_state(recovered.input_connection))

    try:
        await recovered.disconnect()
    except Exception:
        LOG.exception("Error during final recovered-client disconnect")

    try:
        await initial.disconnect()
    except Exception:
        LOG.exception("Error during final initial-client disconnect")

    LOG.info("TEST COMPLETE")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diagnose LG webOS stale WebSocket behavior after Wi-Fi loss."
    )
    parser.add_argument("host", help="LG TV IP address or hostname, e.g. 192.168.0.224")
    parser.add_argument(
        "--client-key",
        default=None,
        help=(
            "Existing LG webOS client key. Optional: if omitted, the TV may ask "
            "for pairing approval and the obtained key will be reused."
        ),
    )
    parser.add_argument(
        "--connect-timeout",
        type=float,
        default=2.0,
        help="aiowebostv WebSocket connection timeout in seconds (default: 2).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable all DEBUG logs on the console as well as in the log file.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = Path.cwd() / f"lg_websocket_recovery_{stamp}.log"

    setup_logging(log_path, args.verbose)
    LOG.info("Log file: %s", log_path)

    try:
        return asyncio.run(async_main(args))
    except KeyboardInterrupt:
        LOG.warning("Interrupted by user")
        return 130
    except Exception:
        LOG.exception("Fatal error")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
