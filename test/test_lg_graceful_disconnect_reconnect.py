#!/usr/bin/env python3
"""
LG webOS graceful-disconnect / reconnect diagnostic.

Purpose
-------
Determine whether a CLEAN WebSocket shutdown before network loss prevents
the temporary reconnect block observed after an abrupt Wi-Fi outage.

Sequence
--------
1. Connect normally to the TV.
2. Verify the connection with get_power_state().
3. Call disconnect(), but override aiowebostv's closeout to enforce a STRICT order:
   INPUT WebSocket close -> wait LG CLOSE reply -> MAIN WebSocket close ->
   wait LG CLOSE reply -> ClientSession close. RX tasks stay alive until both
   WebSocket closing handshakes are complete.
4. ONLY AFTER "CLEAN DISCONNECT COMPLETE" appears:
      - disable PC Wi-Fi for ~60 seconds
      - re-enable Wi-Fi
      - press ENTER
5. Probe TCP 3000/3001.
6. Create a completely NEW WebOsClient with the SAME client key.
7. Attempt ONE full reconnect only (no retry loop).

If reconnect works immediately, graceful shutdown prevents the LG-side block.
If reconnect still hangs at the WebSocket handshake, the block is not caused
only by an unclean old WebSocket session.

Usage:
    python test_lg_graceful_disconnect_reconnect.py 192.168.1.118 \
        --client-key YOUR_KEY --verbose
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

from aiohttp import ClientWebSocketResponse
from aiowebostv import WebOsClient

LOG = logging.getLogger("lg_graceful_test")
T = TypeVar("T")

TCP_TIMEOUT = 2.0


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


async def run_stage(name: str, func: Callable[[], Awaitable[T]]) -> T:
    start = time.monotonic()
    LOG.info("STAGE START | %s", name)
    try:
        result = await func()
    except Exception as exc:
        LOG.error(
            "STAGE FAIL  | %-30s | %.3fs | %s: %r",
            name,
            time.monotonic() - start,
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        raise
    LOG.info(
        "STAGE OK    | %-30s | %.3fs",
        name,
        time.monotonic() - start,
    )
    return result


class DiagnosticWebOsClient(WebOsClient):
    """aiowebostv client with detailed connect and STRICT graceful close."""

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

    @staticmethod
    def _transport_state(ws) -> str:
        if ws is None:
            return "none"
        try:
            transport = ws.get_extra_info("socket")
            peer = ws.get_extra_info("peername")
            return f"peer={peer!r}, socket={transport!r}"
        except Exception as exc:
            return f"transport-state-error={exc!r}"

    async def _await_uncancellable(self, awaitable):
        """Finish a cleanup operation even though connect_handler was cancelled.

        asyncio.gather() already returns a Future, while websocket.close() returns
        a coroutine. ensure_future() correctly handles both.
        """
        task = asyncio.ensure_future(awaitable)
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                # disconnect() cancels connect_handler to enter its finally block.
                # The cleanup task itself is shielded and must be allowed to finish.
                continue
        return task.result()

    async def _close_one_ws(self, label, ws):
        if ws is None:
            LOG.info("%s CLOSE     | no socket", label)
            return

        LOG.info("%s PRE-CLOSE | %s", label, ws_state(ws))
        LOG.info("%s TRANSPORT | %s", label, self._transport_state(ws))
        started = time.monotonic()
        try:
            result = await self._await_uncancellable(ws.close())
            LOG.info(
                "%s CLOSE OK  | result=%r | %.3fs | %s",
                label,
                result,
                time.monotonic() - started,
                ws_state(ws),
            )
        except Exception as exc:
            LOG.error(
                "%s CLOSE FAIL| %.3fs | %s: %r | %s",
                label,
                time.monotonic() - started,
                type(exc).__name__,
                exc,
                ws_state(ws),
                exc_info=True,
            )
            raise

    async def _closeout_tasks(self, main_ws, input_ws):
        """
        TRUE graceful WebSocket shutdown.

        Critical detail:
        Do NOT cancel aiowebostv's RX tasks before websocket.close().
        aiohttp receive() sets close_code=1006 when it is cancelled. Once 1006
        is set, close() sends a CLOSE frame but does not wait for the peer's
        CLOSE reply, so the shutdown is no longer verifiably graceful.

        Correct order:
          1. leave RX tasks alive
          2. close INPUT WebSocket and wait for LG's CLOSE reply
          3. close MAIN WebSocket and wait for LG's CLOSE reply
          4. only then cancel remaining callback/RX tasks
          5. close ClientSession
        """
        LOG.info("=" * 80)
        LOG.info("TRUE GRACEFUL CLOSEOUT START")
        LOG.info("MAIN BEFORE  | %s", ws_state(main_ws))
        LOG.info("INPUT BEFORE | %s", ws_state(input_ws))

        started = time.monotonic()

        # Keep RX tasks alive: aiohttp close() knows how to wake a concurrent
        # receive() and coordinate the WebSocket closing handshake.
        await self._close_one_ws("INPUT", input_ws)
        await self._close_one_ws("MAIN ", main_ws)

        LOG.info(
            "WEBSOCKET HANDSHAKES COMPLETE | %.3fs",
            time.monotonic() - started,
        )

        # Only now stop any tasks that remain.
        callback_tasks = list(self.callback_tasks.values())
        rx_tasks = list(self._rx_tasks)
        self._cancel_tasks()

        pending_tasks = [
            task
            for task in [*callback_tasks, *rx_tasks]
            if not task.done()
        ]
        if pending_tasks:
            await self._await_uncancellable(
                asyncio.gather(*pending_tasks, return_exceptions=True)
            )
        LOG.info("APP/RX TASKS STOPPED | %.3fs", time.monotonic() - started)

        # The connector is closed only after both WS closing handshakes.
        if self.created_client_session and self.client_session is not None:
            session_started = time.monotonic()
            await self._await_uncancellable(self.close_client_session())
            LOG.info(
                "CLIENT SESSION CLOSED | %.3fs",
                time.monotonic() - session_started,
            )

        self.connection = None
        self.input_connection = None
        self.do_state_update = False
        self.tv_state.clear()

        callbacks = [
            asyncio.create_task(callback(self.tv_state))
            for callback in self.state_update_callbacks
        ]
        if callbacks:
            await self._await_uncancellable(
                asyncio.gather(*callbacks, return_exceptions=True)
            )

        LOG.info("MAIN AFTER   | %s", ws_state(main_ws))
        LOG.info("INPUT AFTER  | %s", ws_state(input_ws))
        LOG.info(
            "TRUE GRACEFUL CLOSEOUT COMPLETE | %.3fs",
            time.monotonic() - started,
        )
        LOG.info("=" * 80)


async def tcp_probe(host: str, port: int) -> bool:
    started = time.monotonic()
    writer = None
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=TCP_TIMEOUT,
        )
        LOG.info(
            "TCP OK        | %s:%d | %.3fs",
            host,
            port,
            time.monotonic() - started,
        )
        return True
    except Exception as exc:
        LOG.warning(
            "TCP FAIL      | %s:%d | %.3fs | %s: %r",
            host,
            port,
            time.monotonic() - started,
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


async def connect_once(
    host: str,
    client_key: str | None,
    connect_timeout: float,
    label: str,
) -> DiagnosticWebOsClient | None:
    LOG.info("=" * 80)
    LOG.info("%s | creating fresh WebOsClient", label)

    client = DiagnosticWebOsClient(
        host=host,
        client_key=client_key,
        connect_timeout=connect_timeout,
    )

    started = time.monotonic()
    try:
        result = await client.connect()
        LOG.info(
            "%s | FULL CONNECT SUCCESS | result=%r | %.3fs",
            label,
            result,
            time.monotonic() - started,
        )
        LOG.info("%s | MAIN : %s", label, ws_state(client.connection))
        LOG.info("%s | INPUT: %s", label, ws_state(client.input_connection))
        return client
    except Exception as exc:
        LOG.error(
            "%s | FULL CONNECT FAILED | %.3fs | %s: %r",
            label,
            time.monotonic() - started,
            type(exc).__name__,
            exc,
        )
        try:
            await client.disconnect()
        except Exception as close_exc:
            LOG.warning("%s | cleanup after failed connect: %r", label, close_exc)
        return None


async def prompt_enter(text: str) -> None:
    await asyncio.to_thread(input, text)


async def async_main(args: argparse.Namespace) -> int:
    LOG.info("LG webOS graceful-disconnect/reconnect diagnostic")
    LOG.info("TV: %s", args.host)
    LOG.info("Python: %s", sys.version.replace("\n", " "))
    LOG.info("Host machine: %s", socket.gethostname())
    LOG.info("WebSocket connect timeout: %.1fs", args.connect_timeout)

    # ---- Initial healthy connection
    client = await connect_once(
        args.host,
        args.client_key,
        args.connect_timeout,
        "INITIAL",
    )
    if client is None:
        LOG.error("Initial connection must work before running this experiment.")
        return 2

    if not client.client_key:
        LOG.error("No client key available after initial connection.")
        await client.disconnect()
        return 3

    key = client.client_key
    LOG.info("CLIENT KEY    | %s", key)

    # Ensure we really have a healthy request/response path.
    try:
        power = await asyncio.wait_for(client.get_power_state(), timeout=8.0)
        LOG.info("PRE-CLOSE HEALTH OK | power=%r", power)
    except Exception:
        LOG.exception("Pre-close health check failed; aborting test.")
        try:
            await client.disconnect()
        except Exception:
            pass
        return 4

    # Keep references: aiowebostv will clear self.connection/input_connection.
    old_main = client.connection
    old_input = client.input_connection

    LOG.info("")
    LOG.info("=" * 80)
    LOG.info("PERFORMING CLEAN DISCONNECT NOW")
    LOG.info("Do NOT disable Wi-Fi until the completion message appears.")

    started = time.monotonic()
    try:
        await asyncio.wait_for(client.disconnect(), timeout=args.disconnect_timeout)
    except Exception:
        LOG.exception("CLEAN DISCONNECT FAILED")
        return 5

    LOG.info(
        "disconnect() returned after %.3fs",
        time.monotonic() - started,
    )
    LOG.info("OLD MAIN  AFTER disconnect(): %s", ws_state(old_main))
    LOG.info("OLD INPUT AFTER disconnect(): %s", ws_state(old_input))
    LOG.info("client.is_connected()=%s", client.is_connected())

    # close_code 1000 normally means a normal WebSocket closure. 1006 indicates
    # abnormal closure and would already be suspicious for this experiment.
    clean_codes = {
        getattr(old_main, "close_code", None),
        getattr(old_input, "close_code", None),
    }
    LOG.info("Observed close codes: %s", sorted(str(x) for x in clean_codes))
    LOG.info("")
    LOG.info("******** CLEAN DISCONNECT COMPLETE ********")
    LOG.info("The LG connection has been closed BEFORE the network outage.")
    LOG.info("")
    LOG.info("NOW:")
    LOG.info("  1) Disable this PC's Wi-Fi.")
    LOG.info("  2) Keep Wi-Fi disabled for about 60 seconds.")
    LOG.info("  3) Re-enable Wi-Fi.")
    LOG.info("  4) Wait until normal LAN connectivity is back.")
    LOG.info("  5) Press ENTER here.")
    LOG.info("")
    LOG.info("No LG connection exists during the Wi-Fi outage.")

    await prompt_enter("Press ENTER only AFTER Wi-Fi is back: ")

    LOG.info("")
    LOG.info("=" * 80)
    LOG.info("POST-OUTAGE NETWORK PROBES")
    tcp3000 = await tcp_probe(args.host, 3000)
    tcp3001 = await tcp_probe(args.host, 3001)
    LOG.info("TCP SUMMARY   | 3000=%s 3001=%s", tcp3000, tcp3001)

    LOG.info("")
    LOG.info("ONE fresh reconnect attempt will now be made using the SAME client key.")
    reconnect = await connect_once(
        args.host,
        key,
        args.connect_timeout,
        "POST-OUTAGE",
    )

    if reconnect is None:
        LOG.error("")
        LOG.error("RESULT: RECONNECT FAILED AFTER A CLEAN PRE-OUTAGE DISCONNECT")
        LOG.error(
            "This means an unclean stale WebSocket alone is NOT sufficient "
            "to explain the temporary LG block."
        )
        return 10

    try:
        power = await asyncio.wait_for(reconnect.get_power_state(), timeout=8.0)
        LOG.info("POST-RECONNECT HEALTH OK | power=%r", power)
    except Exception:
        LOG.exception("Reconnect completed but request/response health check failed.")
        try:
            await reconnect.disconnect()
        except Exception:
            pass
        return 11

    LOG.info("")
    LOG.info("RESULT: IMMEDIATE RECONNECT SUCCEEDED AFTER CLEAN PRE-OUTAGE DISCONNECT")
    LOG.info(
        "This strongly supports the hypothesis that the LG-side temporary block "
        "is triggered by losing an ACTIVE WebSocket/TCP session abruptly."
    )

    LOG.info("Final cleanup...")
    try:
        await reconnect.disconnect()
    except Exception:
        LOG.exception("Final disconnect failed")

    return 0


def configure_logging(path: Path, verbose: bool) -> None:
    console_level = logging.DEBUG if verbose else logging.INFO
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03d | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(console_level)
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    logging.getLogger("aiowebostv").setLevel(logging.DEBUG)
    logging.getLogger("aiohttp").setLevel(logging.DEBUG)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Test whether a graceful LG WebSocket disconnect before Wi-Fi loss "
            "prevents the temporary reconnect block."
        )
    )
    parser.add_argument("host", help="LG TV IP, e.g. 192.168.1.118")
    parser.add_argument(
        "--client-key",
        default=None,
        help="Existing LG webOS client key",
    )
    parser.add_argument(
        "--connect-timeout",
        type=float,
        default=2.0,
        help="WebSocket connect timeout in seconds (default: 2)",
    )
    parser.add_argument(
        "--disconnect-timeout",
        type=float,
        default=30.0,
        help="Maximum time allowed for graceful disconnect (default: 30)",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = Path.cwd() / f"lg_graceful_disconnect_{stamp}.log"

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
