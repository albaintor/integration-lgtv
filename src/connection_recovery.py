"""Connection recovery helpers for transient Remote network outages."""

import asyncio
import logging
from asyncio import AbstractEventLoop, CancelledError, Task
from contextlib import suppress
from typing import Any, Awaitable, cast

import aiowebostv
import ucapi
from aiohttp import ClientWebSocketResponse
from aiowebostv import WebOsClient
from ucapi.media_player import States

import lg
from config import LGConfigDevice

_LOG = logging.getLogger("lg")

# ucapi 0.7.x does not expose WIFI_CHANGE yet, but newer Remote firmware can
# send the raw event. Typing it as ucapi.Events keeps IntegrationAPI.listens_to
# compatible while the runtime value remains the protocol event name.
WIFI_CHANGE_EVENT = cast(ucapi.Events, "wifi_change")
WIFI_CONNECTED = "CONNECTED"
WIFI_UNAVAILABLE_STATES = {"DISCONNECTED", "OUT_OF_RANGE"}


class GracefulWebOsClient(WebOsClient):
    """WebOsClient workaround for graceful websocket shutdown.

    aiowebostv 0.9.2 cancels its receive tasks before closing the websocket
    connections. aiohttp turns a cancelled receive into close code 1006, so the
    subsequent websocket close no longer performs a normal CLOSE/CLOSE
    handshake. Some LG TVs then temporarily reject new websocket handshakes
    from that client.

    Keep receive tasks alive until the INPUT and MAIN websocket closing
    handshakes have completed, then perform the normal task/session cleanup.
    """

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


# Temporary compatibility patch until the graceful close fix is available in a
# released aiowebostv version. lg.py imports WebOsClient at module load time,
# while setup_flow imports it later, so patch both references.
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
    """LG device whose reconnect backoff can be interrupted safely."""

    def __init__(
        self,
        device_config: LGConfigDevice,
        loop: AbstractEventLoop | None = None,
    ) -> None:
        super().__init__(device_config, loop=loop)
        self._reconnect_wakeup = asyncio.Event()

    def _ensure_connect_task(self) -> Task[None]:
        """Return the reconnect task and wake its backoff for external callers."""
        task = self._connect_task
        if task is not None and not task.done() and asyncio.current_task() is not task:
            # A command (or another external trigger) arrived while reconnecting.
            # Keep the existing task, but make the next retry immediate. If the
            # current connect attempt is still running, the event stays set until
            # the loop reaches its backoff wait.
            self._reconnect_wakeup.set()
            _LOG.debug(
                "[%s] Reconnect retry requested while connection task is active",
                self._device_config.address,
            )

        return super()._ensure_connect_task()

    def request_reconnect(self, reason: str = "external request") -> Task[None]:
        """Start a reconnect loop or wake the existing loop immediately."""
        self._reconnect_retry = 0
        task = self._connect_task
        if task is not None and not task.done():
            self._reconnect_wakeup.set()
            _LOG.debug(
                "[%s] Wake reconnect loop: %s",
                self._device_config.address,
                reason,
            )
            return task

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
        """Reconnect with an interruptible delay between attempts."""
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

                self._reconnect_retry += 1
                self._attr_state = States.OFF
                if self._reconnect_retry > lg.CONNECTION_RETRIES:
                    _LOG.debug(
                        "[%s] LG not connected abort retries",
                        self._device_config.address,
                    )
                    break

                if self._retry_wakeonlan:
                    self.wakeonlan()

                _LOG.debug(
                    "[%s] LG not connected, retry %s / %s",
                    self._device_config.address,
                    self._reconnect_retry,
                    lg.CONNECTION_RETRIES,
                )

                try:
                    await asyncio.wait_for(
                        self._reconnect_wakeup.wait(), timeout=lg.DEFAULT_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    # Normal backoff expiration. Do not clear the event here: if
                    # a wakeup races with the timeout, keeping it set makes the
                    # following backoff interruptible as well.
                    pass
                else:
                    self._reconnect_wakeup.clear()
                    _LOG.debug(
                        "[%s] Reconnect wait interrupted, retrying immediately",
                        self._device_config.address,
                    )
        except CancelledError:
            _LOG.debug("[%s] LG TV connect task cancelled", self._device_config.address)
        finally:
            self._reconnect_wakeup.clear()
            self._retry_wakeonlan = False
            self._connect_task = None
            self._reconnect_retry = 0
