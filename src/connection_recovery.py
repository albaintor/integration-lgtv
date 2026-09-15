"""Connection recovery helpers for transient Remote network outages."""

import asyncio
import logging
import time
from asyncio import CancelledError, Task
from contextlib import suppress
from typing import Any, Awaitable, cast

import aiohttp
import aiowebostv
import ucapi
from aiohttp import ClientSession, ClientWebSocketResponse, TraceConfig
from aiowebostv import WebOsClient
from aiowebostv.webos_client import (
    CONNECT_TIMEOUT,
    MAIN_WS_MAX_MSG_SIZE,
    WS_PORT,
    WSS_PORT,
)
from ucapi.media_player import States

import lg

_LOG = logging.getLogger("lg")

# Keep LG connections responsive, but avoid treating a short Remote Wi-Fi
# transition as a dead WebSocket. aiohttp waits heartbeat/2 for the PONG, so a
# 30 s heartbeat tolerates about 15 s of missing PONGs before closing.
LG_HEARTBEAT = 30.0

# ucapi 0.7.x does not expose WIFI_CHANGE yet, but newer Remote firmware can
# send the raw event. Typing it as ucapi.Events keeps IntegrationAPI.listens_to
# compatible while the runtime value remains the protocol event name.
WIFI_CHANGE_EVENT = cast(ucapi.Events, "wifi_change")
WIFI_CONNECTED = "CONNECTED"
WIFI_UNAVAILABLE_STATES = {"DISCONNECTED", "OUT_OF_RANGE"}


class GracefulWebOsClient(WebOsClient):
    """webOS client tuned for Remote standby/network transitions.

    Differences from aiowebostv 0.9.2:
    - use a 30 second heartbeat instead of 5 seconds;
    - try the modern secure webOS endpoint (WSS/3001) before legacy WS/3000,
      matching the connection path used by LG ConnectSDK on current TVs;
    - emit detailed TCP/TLS/HTTP/SSAP diagnostics for reconnect analysis;
    - close INPUT and MAIN WebSockets before cancelling receive tasks so a
      normal CLOSE/CLOSE handshake can complete.

    The graceful close fixes abnormal local cleanup, but is intentionally not
    treated as the root cause of the long reconnect timeout under investigation.
    """

    def __init__(
        self,
        host: str,
        client_key: str | None = None,
        connect_timeout: float = CONNECT_TIMEOUT,
        heartbeat: float = LG_HEARTBEAT,
        client_session: ClientSession | None = None,
    ) -> None:
        super().__init__(
            host=host,
            client_key=client_key,
            connect_timeout=connect_timeout,
            heartbeat=heartbeat,
            client_session=client_session,
        )

    @staticmethod
    def _elapsed(started: float | None) -> str:
        if started is None:
            return "?"
        return f"{time.monotonic() - started:.3f}s"

    async def _trace_request_start(
        self, session: ClientSession, ctx: Any, params: Any
    ) -> None:
        del session
        ctx.lg_request_started = time.monotonic()
        ctx.lg_request_url = str(getattr(params, "url", "?"))
        _LOG.debug(
            "[%s] LG NET HTTP start: %s %s",
            self.host,
            getattr(params, "method", "?"),
            ctx.lg_request_url,
        )

    async def _trace_connection_create_start(
        self, session: ClientSession, ctx: Any, params: Any
    ) -> None:
        del session, params
        ctx.lg_connection_started = time.monotonic()
        _LOG.debug(
            "[%s] LG NET TCP/TLS connect start: %s",
            self.host,
            getattr(ctx, "lg_request_url", "?"),
        )

    async def _trace_connection_create_end(
        self, session: ClientSession, ctx: Any, params: Any
    ) -> None:
        del session, params
        _LOG.debug(
            "[%s] LG NET TCP/TLS ready: %s in %s",
            self.host,
            getattr(ctx, "lg_request_url", "?"),
            self._elapsed(getattr(ctx, "lg_connection_started", None)),
        )

    async def _trace_request_headers_sent(
        self, session: ClientSession, ctx: Any, params: Any
    ) -> None:
        del session, params
        _LOG.debug(
            "[%s] LG NET HTTP Upgrade headers sent: %s in %s",
            self.host,
            getattr(ctx, "lg_request_url", "?"),
            self._elapsed(getattr(ctx, "lg_request_started", None)),
        )

    async def _trace_request_end(
        self, session: ClientSession, ctx: Any, params: Any
    ) -> None:
        del session
        response = getattr(params, "response", None)
        _LOG.debug(
            "[%s] LG NET HTTP response: %s status=%s in %s",
            self.host,
            getattr(ctx, "lg_request_url", "?"),
            getattr(response, "status", "?"),
            self._elapsed(getattr(ctx, "lg_request_started", None)),
        )

    async def _trace_request_exception(
        self, session: ClientSession, ctx: Any, params: Any
    ) -> None:
        del session
        exception = getattr(params, "exception", None)
        _LOG.warning(
            "[%s] LG NET HTTP exception: %s after %s: %s: %r",
            self.host,
            getattr(ctx, "lg_request_url", "?"),
            self._elapsed(getattr(ctx, "lg_request_started", None)),
            type(exception).__name__ if exception is not None else "?",
            exception,
        )

    def _build_trace_config(self) -> TraceConfig:
        trace = TraceConfig()
        trace.on_request_start.append(self._trace_request_start)
        trace.on_connection_create_start.append(self._trace_connection_create_start)
        trace.on_connection_create_end.append(self._trace_connection_create_end)
        trace.on_request_headers_sent.append(self._trace_request_headers_sent)
        trace.on_request_end.append(self._trace_request_end)
        trace.on_request_exception.append(self._trace_request_exception)
        return trace

    def _ensure_client_session(self) -> None:
        """Create an aiohttp session with connection-stage diagnostics."""
        if self.client_session is None:
            self.client_session = ClientSession(trace_configs=[self._build_trace_config()])
            self.created_client_session = True

    async def _ws_connect(
        self, uri: str, max_msg_size: int
    ) -> ClientWebSocketResponse:
        """Create one WebSocket and log the complete connection stage."""
        started = time.monotonic()
        _LOG.debug(
            "[%s] LG WS connect start: %s heartbeat=%.1fs",
            self.host,
            uri,
            self.heartbeat,
        )
        try:
            ws = await super()._ws_connect(uri, max_msg_size)
        except CancelledError:
            _LOG.debug(
                "[%s] LG WS connect cancelled: %s after %.3fs",
                self.host,
                uri,
                time.monotonic() - started,
            )
            raise
        except Exception as ex:
            _LOG.warning(
                "[%s] LG WS connect failed: %s after %.3fs: %s: %r",
                self.host,
                uri,
                time.monotonic() - started,
                type(ex).__name__,
                ex,
            )
            raise

        _LOG.debug(
            "[%s] LG WS connected: %s in %.3fs local=%r peer=%r ssl=%s",
            self.host,
            uri,
            time.monotonic() - started,
            ws.get_extra_info("sockname"),
            ws.get_extra_info("peername"),
            ws.get_extra_info("ssl_object") is not None,
        )
        return ws

    async def _create_main_ws(self) -> ClientWebSocketResponse:
        """Prefer current webOS WSS/3001 and fall back to legacy WS/3000."""
        secure_uri = f"wss://{self.host}:{WSS_PORT}"
        try:
            return await self._ws_connect(secure_uri, MAIN_WS_MAX_MSG_SIZE)
        except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as ex:
            # Keep legacy webOS support. The preceding diagnostics still show
            # whether 3001 failed before TCP/TLS, during TLS, or after Upgrade.
            _LOG.debug(
                "[%s] WSS/3001 unavailable (%r), trying legacy WS/%s",
                self.host,
                ex,
                WS_PORT,
            )

        legacy_uri = f"ws://{self.host}:{WS_PORT}"
        return await self._ws_connect(legacy_uri, MAIN_WS_MAX_MSG_SIZE)

    async def _get_hello_info(self, ws: ClientWebSocketResponse) -> None:
        started = time.monotonic()
        _LOG.debug("[%s] LG SSAP HELLO start", self.host)
        try:
            await super()._get_hello_info(ws)
        except Exception as ex:
            _LOG.warning(
                "[%s] LG SSAP HELLO failed after %.3fs: %s: %r",
                self.host,
                time.monotonic() - started,
                type(ex).__name__,
                ex,
            )
            raise
        _LOG.debug(
            "[%s] LG SSAP HELLO completed in %.3fs",
            self.host,
            time.monotonic() - started,
        )

    async def _get_pre_reg_system_info(self, ws: ClientWebSocketResponse) -> None:
        started = time.monotonic()
        _LOG.debug("[%s] LG SSAP pre-registration system info start", self.host)
        try:
            await super()._get_pre_reg_system_info(ws)
        except Exception as ex:
            _LOG.warning(
                "[%s] LG SSAP pre-registration system info failed after %.3fs: %s: %r",
                self.host,
                time.monotonic() - started,
                type(ex).__name__,
                ex,
            )
            raise
        _LOG.debug(
            "[%s] LG SSAP pre-registration system info completed in %.3fs",
            self.host,
            time.monotonic() - started,
        )

    async def _check_registration(self, ws: ClientWebSocketResponse) -> None:
        started = time.monotonic()
        _LOG.debug("[%s] LG SSAP REGISTER start", self.host)
        try:
            await super()._check_registration(ws)
        except Exception as ex:
            _LOG.warning(
                "[%s] LG SSAP REGISTER failed after %.3fs: %s: %r",
                self.host,
                time.monotonic() - started,
                type(ex).__name__,
                ex,
            )
            raise
        _LOG.debug(
            "[%s] LG SSAP REGISTER completed in %.3fs",
            self.host,
            time.monotonic() - started,
        )

    @staticmethod
    async def _finish_cleanup(awaitable: Awaitable[Any]) -> Any:
        """Finish one cleanup operation even while connect_handler is cancelled."""
        task = asyncio.ensure_future(awaitable)
        while not task.done():
            try:
                await asyncio.shield(task)
            except CancelledError:
                # disconnect() cancels connect_handler to enter its finally
                # block. The websocket closing handshake itself must finish.
                continue
        return task.result()

    async def _closeout_tasks(
        self,
        main_ws: ClientWebSocketResponse | None,
        input_ws: ClientWebSocketResponse | None,
    ) -> None:
        """Close websocket handshakes before cancelling receive tasks."""
        # The input websocket depends on the main SSAP session, close it first.
        if input_ws is not None and not input_ws.closed:
            await self._finish_cleanup(input_ws.close())
        if main_ws is not None and not main_ws.closed:
            await self._finish_cleanup(main_ws.close())

        _LOG.debug(
            "[%s] Graceful websocket close completed: main=%s input=%s",
            self.host,
            main_ws.close_code if main_ws is not None else None,
            input_ws.close_code if input_ws is not None else None,
        )

        # Mirror aiowebostv cleanup, but only after both WebSocket CLOSE
        # handshakes have completed.
        closeout: set[asyncio.Task[Any]] = set()
        self._cancel_tasks()

        if callback_tasks := set(self.callback_tasks.values()):
            closeout.update(callback_tasks)

        closeout.update(self._rx_tasks)

        if self.created_client_session:
            closeout.add(asyncio.create_task(self.close_client_session()))

        self.connection = None
        self.input_connection = None
        self.do_state_update = False
        self.tv_state.clear()

        for callback in self.state_update_callbacks:
            closeout.add(asyncio.create_task(callback(self.tv_state)))

        if not closeout:
            return

        closeout_task = asyncio.create_task(asyncio.wait(closeout))
        while not closeout_task.done():
            with suppress(CancelledError):
                await asyncio.shield(closeout_task)


# Temporary compatibility patch until the connection-profile and graceful-close
# changes are available in a released aiowebostv version. lg.py imports
# WebOsClient at module load time, while setup_flow imports it later, so patch
# both references.
setattr(aiowebostv, "WebOsClient", GracefulWebOsClient)
setattr(lg, "WebOsClient", GracefulWebOsClient)


class IntegrationAPI(ucapi.IntegrationAPI):
    """Integration API with forward-compatible support for ``wifi_change``."""

    async def _handle_ws_event_msg(
        self, websocket: Any, msg: str, msg_data: dict[str, Any] | None
    ) -> None:
        if msg == WIFI_CHANGE_EVENT:
            data = msg_data or {}
            self._events.emit(
                WIFI_CHANGE_EVENT,
                websocket=websocket,
                state=data.get("state"),
                msg_data=data,
            )
            return

        await super()._handle_ws_event_msg(websocket, msg, msg_data)


class LGDevice(lg.LGDevice):
    """LG device with one stable reconnect state machine."""

    def _ensure_connect_task(self) -> Task[None]:
        """Return the active reconnect task without forcing another attempt."""
        task = self._connect_task
        if task is not None and not task.done():
            if asyncio.current_task() is not task:
                _LOG.debug(
                    "[%s] Reconnect already active; keep current attempt/backoff",
                    self._device_config.address,
                )
            return task

        return super()._ensure_connect_task()

    def request_reconnect(self, reason: str = "external request") -> Task[None]:
        """Start one reconnect loop, or reuse the one already running."""
        task = self._connect_task
        if task is not None and not task.done():
            _LOG.debug(
                "[%s] Reconnect already active, ignore duplicate trigger: %s",
                self._device_config.address,
                reason,
            )
            return task

        self._reconnect_retry = 0
        _LOG.debug(
            "[%s] Start reconnect loop: %s",
            self._device_config.address,
            reason,
        )
        return self._ensure_connect_task()

    @property
    def reconnect_active(self) -> bool:
        """Return whether a reconnect loop is currently active."""
        return self._connect_task is not None and not self._connect_task.done()

    async def _connect_loop(self) -> None:
        """Reconnect serially with a stable backoff between attempts.

        The retry count is local so button presses cannot reset an active loop
        through lg.retry_call_command(). This mirrors LG ConnectSDK's approach:
        an existing connection attempt stays authoritative until it completes.
        """
        retry_count = 0
        try:
            while True:
                try:
                    await self.connect()
                    if self._tv.tv_state.is_on:
                        _LOG.debug(
                            "[%s] LG TV connection succeeded",
                            self._device_config.address,
                        )
                        self._update_picture_modes()
                        break
                except CancelledError:
                    _LOG.debug(
                        "[%s] LG TV connect task cancelled",
                        self._device_config.address,
                    )
                    break
                # pylint: disable=W0718
                except Exception as ex:
                    _LOG.warning(
                        "[%s] LG TV connection failed %s",
                        self._device_config.address,
                        ex,
                    )

                retry_count += 1
                self._reconnect_retry = retry_count
                self._attr_state = States.OFF
                if retry_count > lg.CONNECTION_RETRIES:
                    _LOG.debug(
                        "[%s] LG not connected abort retries",
                        self._device_config.address,
                    )
                    break

                if self._retry_wakeonlan:
                    self.wakeonlan()

                _LOG.debug(
                    "[%s] LG not connected, retry %s / %s in %ss",
                    self._device_config.address,
                    retry_count,
                    lg.CONNECTION_RETRIES,
                    lg.DEFAULT_TIMEOUT,
                )
                await asyncio.sleep(lg.DEFAULT_TIMEOUT)
        except CancelledError:
            _LOG.debug("[%s] LG TV connect task cancelled", self._device_config.address)
        finally:
            self._retry_wakeonlan = False
            self._connect_task = None
            self._reconnect_retry = 0
