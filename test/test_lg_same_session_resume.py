#!/usr/bin/env python3
"""
LG webOS same-session resume test.

Goal:
- Connect once to the TV.
- Disable aiohttp WebSocket heartbeat so the client does NOT close itself when
  Wi-Fi disappears.
- Do NOT call disconnect().
- Do NOT reconnect.
- Cut PC Wi-Fi for ~60 seconds, restore it, then test the SAME existing
  main and input WebSocket connections.

Usage:
    python test_lg_same_session_resume.py 192.168.1.118 --client-key YOUR_KEY --verbose
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import ClientWebSocketResponse
from aiowebostv import WebOsClient

LOG = logging.getLogger("lg_same_session")


def ws_state(ws: ClientWebSocketResponse | None) -> str:
    if ws is None:
        return "none"
    try:
        return (
            f"closed={ws.closed}, close_code={ws.close_code}, "
            f"exception={ws.exception()!r}"
        )
    except Exception as exc:
        return f"state-error={exc!r}"


class NoHeartbeatWebOsClient(WebOsClient):
    """WebOsClient whose aiohttp WebSockets have no automatic heartbeat."""

    async def _ws_connect(
        self, uri: str, max_msg_size: int
    ) -> ClientWebSocketResponse:
        LOG.info("WS CONNECT    | %s | heartbeat=None", uri)

        if TYPE_CHECKING:
            assert self.client_session is not None

        async with asyncio.timeout(self.timeout_connect):
            return await self.client_session.ws_connect(
                uri,
                heartbeat=None,
                ssl=False,
                max_msg_size=max_msg_size,
            )


async def user_input(prompt: str) -> str:
    return await asyncio.to_thread(input, prompt)


async def test_same_session(client: NoHeartbeatWebOsClient) -> bool:
    LOG.info("")
    LOG.info("=" * 78)
    LOG.info("TEST SAME EXISTING SESSION -- NO RECONNECT")
    LOG.info("Before | is_connected=%s", client.is_connected())
    LOG.info("Before | MAIN : %s", ws_state(client.connection))
    LOG.info("Before | INPUT: %s", ws_state(client.input_connection))

    main_ok = False
    input_ok = False

    start = time.monotonic()
    try:
        power = await asyncio.wait_for(client.get_power_state(), timeout=8.0)
        main_ok = True
        LOG.info(
            "SAME MAIN OK  | get_power_state=%r | %.3fs",
            power,
            time.monotonic() - start,
        )
    except Exception as exc:
        LOG.error(
            "SAME MAIN FAIL| %.3fs | %s: %r",
            time.monotonic() - start,
            type(exc).__name__,
            exc,
            exc_info=True,
        )

    LOG.info("After MAIN | MAIN : %s", ws_state(client.connection))
    LOG.info("After MAIN | INPUT: %s", ws_state(client.input_connection))

    start = time.monotonic()
    try:
        await asyncio.wait_for(client.button("INFO"), timeout=8.0)
        input_ok = True
        LOG.info(
            "SAME INPUT OK | INFO command sent | %.3fs",
            time.monotonic() - start,
        )
    except Exception as exc:
        LOG.error(
            "SAME INPUT FAIL| %.3fs | %s: %r",
            time.monotonic() - start,
            type(exc).__name__,
            exc,
            exc_info=True,
        )

    LOG.info("After INPUT | MAIN : %s", ws_state(client.connection))
    LOG.info("After INPUT | INPUT: %s", ws_state(client.input_connection))
    LOG.info("After tests | is_connected=%s", client.is_connected())

    if main_ok and input_ok:
        LOG.info("RESULT: SAME SESSION RESUMED SUCCESSFULLY")
        return True

    if main_ok:
        LOG.warning("RESULT: MAIN resumed but INPUT socket failed")
    elif input_ok:
        LOG.warning("RESULT: INPUT worked but MAIN request failed")
    else:
        LOG.warning("RESULT: SAME SESSION DID NOT RESUME")

    return False


async def async_main(args: argparse.Namespace) -> int:
    LOG.info("LG webOS SAME-SESSION resume diagnostic")
    LOG.info("TV: %s", args.host)
    LOG.info("Heartbeat: DISABLED")
    LOG.info("No disconnect/reconnect will occur during the test")

    client = NoHeartbeatWebOsClient(
        host=args.host,
        client_key=args.client_key,
        connect_timeout=args.connect_timeout,
        heartbeat=0,
    )

    LOG.info("Connecting initial session...")
    try:
        result = await client.connect()
    except Exception:
        LOG.exception("Initial connection failed")
        return 2

    if not result:
        LOG.error("Initial connection returned False")
        return 2

    LOG.info("INITIAL OK    | client_key=%s", client.client_key)
    LOG.info("INITIAL MAIN  | %s", ws_state(client.connection))
    LOG.info("INITIAL INPUT | %s", ws_state(client.input_connection))

    if not client.client_key:
        LOG.error("No client key available")
        return 3

    LOG.info("")
    LOG.info("=== MANUAL TEST ===")
    LOG.info("1. Disable Wi-Fi on this PC.")
    LOG.info("2. Keep it disabled for about 60 seconds.")
    LOG.info("3. Re-enable Wi-Fi.")
    LOG.info("4. Do NOT restart the script.")
    LOG.info("5. Once network connectivity is back, press ENTER here.")
    LOG.info("")
    LOG.info("CRITICAL: no network request is sent while you perform the outage.")

    await user_input("Press ENTER only AFTER Wi-Fi is back: ")

    LOG.info("")
    LOG.info("Wi-Fi reported restored by user")
    LOG.info("Session before first post-outage traffic:")
    LOG.info("MAIN : %s", ws_state(client.connection))
    LOG.info("INPUT: %s", ws_state(client.input_connection))

    ok = await test_same_session(client)

    LOG.info("")
    LOG.info("Test complete. Performing normal final disconnect now.")
    try:
        await client.disconnect()
    except Exception:
        LOG.exception("Final disconnect failed")

    return 0 if ok else 1


def configure_logging(path: Path, verbose: bool) -> None:
    console_level = logging.DEBUG if verbose else logging.INFO

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s.%(msecs)03d | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(console_level)
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    logging.getLogger("aiowebostv").setLevel(logging.DEBUG)
    logging.getLogger("aiohttp").setLevel(logging.DEBUG)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test whether an LG webOS WebSocket session resumes after Wi-Fi loss."
    )
    parser.add_argument("host", help="TV IP, e.g. 192.168.1.118")
    parser.add_argument(
        "--client-key",
        default=None,
        help="Existing LG webOS pairing key",
    )
    parser.add_argument(
        "--connect-timeout",
        type=float,
        default=2.0,
        help="Initial WebSocket connect timeout (default: 2s)",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = Path.cwd() / f"lg_same_session_resume_{stamp}.log"

    configure_logging(log_path, args.verbose)
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
