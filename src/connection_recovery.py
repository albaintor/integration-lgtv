"""Connection recovery helpers for transient Remote network outages."""

import asyncio
import logging
from asyncio import AbstractEventLoop, CancelledError, Task
from typing import Any, cast

import ucapi
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
        if (
            task is not None
            and not task.done()
            and asyncio.current_task() is not task
        ):
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
            _LOG.debug(
                "[%s] LG TV connect task cancelled", self._device_config.address
            )
        finally:
            self._reconnect_wakeup.clear()
            self._retry_wakeonlan = False
            self._connect_task = None
            self._reconnect_retry = 0
