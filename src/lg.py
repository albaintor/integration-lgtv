"""
This module implements the AVR AVR receiver communication of the Remote Two integration driver.

:copyright: (c) 2023 by Unfolded Circle ApS.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

# pylint: disable = C0302
import asyncio
import logging
import socket
import struct
import time
from asyncio import AbstractEventLoop, Lock, shield
from enum import IntEnum
from functools import wraps
from typing import (
    Any,
    Awaitable,
    Callable,
    Concatenate,
    Coroutine,
    ParamSpec,
    TypeVar,
    cast,
)

import ucapi
from aiohttp import WSMessageTypeError
from aiowebostv import WebOsClient, WebOsTvCommandError, WebOsTvState, endpoints
from pyee.asyncio import AsyncIOEventEmitter
from ucapi.media_player import Attributes as MediaAttr
from ucapi.media_player import Features, MediaType, States

from config import LGConfigDevice
from const import (
    LG_ADDITIONAL_ENDPOINTS,
    LG_FEATURES,
    LG_SOUND_OUTPUTS,
    LIVE_TV_APP_ID,
    WEBOSTV_EXCEPTIONS,
)

_LOG = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 2
BUFFER_LIFETIME = 30
CONNECTION_RETRIES = 20

INIT_APPS_LAUNCH_DELAY = 10

SOURCE_IS_APP = "isApp"


class LGState(IntEnum):
    """State of device."""

    OFF = 0
    STANDBY = 1
    ON = 2


class Events(IntEnum):
    """Internal driver events."""

    CONNECTING = 0
    CONNECTED = 1
    DISCONNECTED = 2
    ERROR = 3
    UPDATE = 4
    # IP_ADDRESS_CHANGED = 6


_LGDeviceT = TypeVar("_LGDeviceT", bound="LGDevice")
_P = ParamSpec("_P")


async def retry_call_command(
    timeout: float,
    bufferize: bool,
    func: Callable[Concatenate[_LGDeviceT, _P], Awaitable[ucapi.StatusCodes | None]],
    obj: _LGDeviceT,
    *args: _P.args,
    **kwargs: _P.kwargs,
) -> ucapi.StatusCodes:
    """Retry call command when failed."""
    # Launch reconnection task if not active
    # pylint: disable = W0212
    if not obj._connect_task:
        obj._connect_task = asyncio.create_task(obj._connect_loop())
        await asyncio.sleep(0)
    # If the command should be bufferized (and retried later) add it to the list and returns OK
    if bufferize:
        _LOG.debug("[%s] Bufferize command %s %s", obj._device_config.address, func, args)
        obj._buffered_callbacks[time.time()] = {"object": obj, "function": func, "args": args, "kwargs": kwargs}
        return ucapi.StatusCodes.OK
    try:
        # Else (no bufferize) wait (not more than "timeout" seconds) for the connection to complete
        async with asyncio.timeout(max(timeout - 1, 1)):
            await shield(obj._connect_task)
    except asyncio.TimeoutError:
        # (Re)connection failed at least at given time
        if obj.state == States.OFF:
            log_function = _LOG.debug
        else:
            log_function = _LOG.error
        # Try to send the command anyway if connection timed out
        log_function("[%s] Timeout for reconnect, command will probably fail", obj._device_config.address)
    _LOG.debug("[%s] Executing command %s on [%s]", obj._device_config.address, func.__name__, obj._name)
    await func(obj, *args, **kwargs)
    return ucapi.StatusCodes.OK


def retry(*, timeout: float = 5, bufferize=False) -> Callable[
    [Callable[_P, Awaitable[ucapi.StatusCodes]]],
    Callable[Concatenate[_LGDeviceT, _P], Coroutine[Any, Any, ucapi.StatusCodes | None]],
]:
    """Retry command."""

    def decorator(
        func: Callable[Concatenate[_LGDeviceT, _P], Awaitable[ucapi.StatusCodes | None]],
    ) -> Callable[Concatenate[_LGDeviceT, _P], Coroutine[Any, Any, ucapi.StatusCodes | None]]:
        @wraps(func)
        async def wrapper(obj: _LGDeviceT, *args: _P.args, **kwargs: _P.kwargs) -> ucapi.StatusCodes:
            """Wrap all command methods."""
            # pylint: disable = W0212
            try:
                if obj.available:
                    await func(obj, *args, **kwargs)
                    return ucapi.StatusCodes.OK
                _LOG.debug(
                    "[%s] Device is unavailable, connecting before executing command...", obj._device_config.address
                )
                return await retry_call_command(timeout, bufferize, func, obj, *args, **kwargs)
            # New bug "Received message 8:1008 is not WSMsgType.TEXT" for some commands (power_off at least)
            # pylint: disable = W0718
            except Exception as ex:
                if obj.state == States.OFF:
                    log_function = _LOG.debug
                else:
                    log_function = _LOG.error
                log_function(
                    "[%s] Error calling %s on [%s]: %r trying to reconnect",
                    obj._device_config.address,
                    func.__name__,
                    obj._name,
                    ex,
                )
                try:
                    return await retry_call_command(timeout, bufferize, func, obj, *args, **kwargs)
                except (WEBOSTV_EXCEPTIONS, WSMessageTypeError) as wex:
                    log_function(
                        "[%s] Error calling %s on [%s]: %r",
                        obj._device_config.address,
                        func.__name__,
                        obj._name,
                        wex,
                    )
                    return ucapi.StatusCodes.BAD_REQUEST
            # pylint: disable = W0718
            # except Exception as ex:
            #     _LOG.error("[%s] Unknown error %s %s", obj._device_config.address, func.__name__, ex)
            #     return ucapi.StatusCodes.BAD_REQUEST

        return wrapper

    return decorator


def create_magic_packet(mac_address: str) -> bytes:
    """Create a magic packet to wake on LAN."""
    addr_byte = mac_address.split(":")
    hw_addr = struct.pack(
        "BBBBBB",
        int(addr_byte[0], 16),
        int(addr_byte[1], 16),
        int(addr_byte[2], 16),
        int(addr_byte[3], 16),
        int(addr_byte[4], 16),
        int(addr_byte[5], 16),
    )
    return b"\xff" * 6 + hw_addr * 16


class LGDevice:
    """Representing a LG TV Device."""

    def __init__(
        self,
        device_config: LGConfigDevice,
        loop: AbstractEventLoop | None = None,
    ):
        """Create instance with given IP or hostname of AVR."""
        # identifier from configuration
        self._connecting = False
        self._device_config = device_config  # For reconnection
        self.id: str = device_config.id
        # friendly name from configuration
        self._name: str = device_config.name
        self._model_name = device_config.name
        self._serial_number = ""
        self.event_loop = loop or asyncio.get_running_loop()
        self.events = AsyncIOEventEmitter(self.event_loop)
        self._tv: WebOsClient = WebOsClient(host=device_config.address, client_key=device_config.key)
        self._available: bool = True
        self._volume = 0
        self._attr_is_volume_muted = False
        self._active_source = None
        self._sources = {}
        self._unique_id: str | None = None
        self._supported_features = LG_FEATURES
        self._paused = False
        self._media_type = MediaType.VIDEO
        self._media_title = ""
        self._media_image_url = ""
        self._attr_state = States.OFF
        self._connect_task = None
        self._buffered_callbacks = {}
        self._connect_lock = Lock()
        self._reconnect_retry = 0
        self._sound_output = None
        self._retry_wakeonlan = False

        _LOG.debug("[%s] LG TV created", device_config.address)

    def update_config(self, device_config: LGConfigDevice):
        """Update existing configuration."""
        self._device_config = device_config

    async def register_websocket_events(self):
        """Activate websocket for listening if wanted. the websocket has to be recreated when the device goes off."""
        _LOG.info("[%s] LG TV Register websocket events", self._device_config.address)

        async def _on_state_changed(state: WebOsTvState):
            """State changed callback."""
            await self._update_states(self._tv)

            if not state.power_state:
                self._attr_state = States.OFF

            # _LOG.debug("State changed:")
            # _LOG.debug(f"System info: {client.system_info}")
            # _LOG.debug(f"Software info: {client.software_info}")
            # _LOG.debug(f"Hello info: {client.hello_info}")
            # _LOG.debug(f"Channel info: {client.channel_info}")
            # _LOG.debug(f"Apps: {client.apps}")
            # _LOG.debug(f"Inputs: {client.inputs}")
            # _LOG.debug(f"Powered on: {client.power_state}")
            # _LOG.debug(f"App Id: {client.current_app_id}")
            # _LOG.debug(f"Channels: {client.channels}")
            # _LOG.debug(f"Current channel: {client.current_channel}")
            # _LOG.debug(f"Muted: {client.muted}")
            # _LOG.debug(f"Volume: {client.volume}")
            # _LOG.debug(f"Sound output: {client.sound_output}")

        async def _on_sound_output_changed(sound_output: str):
            if sound_output:
                if self._sound_output != sound_output:
                    self._sound_output = sound_output
                    self.events.emit(Events.UPDATE, self.id, {MediaAttr.SOUND_MODE: self.sound_output})

        await self._tv.register_state_update_callback(_on_state_changed)
        await self._tv.subscribe_sound_output(_on_sound_output_changed)

    def _update_sources(self, updated_data: any) -> None:
        """Update list of sources from current source, apps, inputs and configured list."""
        current_source_list = self._sources
        self._sources = {}
        active_source = None
        found_live_tv = False
        for app in self._tv.tv_state.apps.values():
            if app["id"] == LIVE_TV_APP_ID:
                found_live_tv = True
            if app["id"] == self._tv.tv_state.current_app_id:
                active_source = app["title"]
            self._sources[app["title"]] = app
            self._sources[app["title"]][SOURCE_IS_APP] = True

        for source in self._tv.tv_state.inputs.values():
            if source["appId"] == LIVE_TV_APP_ID:
                found_live_tv = True
            if source["appId"] == self._tv.tv_state.current_app_id:
                active_source = source["id"]
            self._sources[source["id"]] = source
            self._sources[source["id"]][SOURCE_IS_APP] = False

        # empty list, TV may be off, keep previous list
        if not self._sources and current_source_list:
            self._sources = current_source_list
        # special handling of live tv since this might
        # not appear in the app or input lists in some cases
        elif not found_live_tv:
            app = {"id": LIVE_TV_APP_ID, "title": "Live TV"}
            if self._tv.tv_state.current_app_id == LIVE_TV_APP_ID:
                active_source = app["title"]
            self._sources["Live TV"] = app
            self._sources[app["title"]][SOURCE_IS_APP] = True

        if (
            not current_source_list and self._sources
        ):  # or (self._sources and list(self._sources.keys()).sort() != list(current_source_list).sort()):
            _LOG.debug("[%s] Source list %s", self._device_config.address, self._sources)
            updated_data[MediaAttr.SOURCE_LIST] = self.source_list

        if active_source != self._active_source:
            _LOG.debug("[%s] Active source %s", self._device_config.address, active_source)
            self._active_source = active_source
            updated_data[MediaAttr.SOURCE] = self._active_source

    async def _update_states(self, data: WebOsClient | None) -> None:
        """Update entity state attributes."""
        # pylint: disable = R0915
        updated_data = {}
        if not self._sources:
            try:
                sources = await self._tv.get_inputs()
                _LOG.info("[%s] Empty sources, retrieve them %s", self._device_config.address, sources)
                await self._tv.set_inputs_state(list(sources.values()))
                await self._tv.set_apps_state(await self._tv.get_apps())
                # pylint: disable = E1101
                await self._tv.set_current_app_state(await self._tv.get_current_app())
            # pylint: disable = W0718
            except Exception:
                pass

        self._update_sources(updated_data)

        # Bug on LG library where power_state not updated, force it
        try:
            # pylint: disable = W0212
            self._tv._power_state = await self._tv.get_power_state()
            # is_on = self._tv.tv_info.is_on
            is_on = self._tv._power_state.get("state", "") == "Active"
        # pylint: disable = W0718
        except Exception:
            is_on = False
        # pylint: disable = W0718
        if data and data.tv_state.sound_output:
            if self._sound_output != data.tv_state.sound_output:
                self._sound_output = data.tv_state.sound_output
                updated_data[MediaAttr.SOUND_MODE] = self.sound_output
        elif self._sound_output is None:
            try:
                self._sound_output = await self._tv.get_sound_output()
                if self._sound_output:
                    updated_data[MediaAttr.SOUND_MODE] = self.sound_output
                _LOG.debug("[%s] Sound output %s", self._device_config.address, self._sound_output)
            except Exception as ex:
                _LOG.warning("[%s] Error extraction of sound output %s", self._device_config.address, ex)

        state = States.ON if is_on else States.OFF
        if state != self.state:
            self._attr_state = state
            updated_data[MediaAttr.STATE] = self.state

        muted = cast(bool, self._tv.tv_state.muted)
        if muted != self._attr_is_volume_muted:
            self._attr_is_volume_muted = muted
            updated_data[MediaAttr.MUTED] = self._attr_is_volume_muted

        if self._tv.tv_state.volume is not None:
            volume = cast(float, self._tv.tv_state.volume)
            if volume != self._volume:
                self._volume = volume
                updated_data[MediaAttr.VOLUME] = self._volume

        media_type = MediaType.VIDEO
        if self._tv.tv_state.current_app_id == LIVE_TV_APP_ID:
            media_type = MediaType.TVSHOW

        if media_type != self._media_type:
            self._media_type = media_type
            updated_data[MediaAttr.MEDIA_TYPE] = self._media_type

        media_title = ""
        if self._tv.tv_state.current_app_id == LIVE_TV_APP_ID and self._tv.tv_state.current_channel is not None:
            media_title = cast(str, self._tv.tv_state.current_channel.get("channelName"))

        if media_title != self._media_title:
            self._media_title = media_title
            updated_data[MediaAttr.MEDIA_TITLE] = self._media_title

        # TODO playing / paused state to update
        media_image_url = ""
        if self._tv.tv_state.current_app_id in self._tv.tv_state.apps:
            icon: str = self._tv.tv_state.apps[self._tv.tv_state.current_app_id]["largeIcon"]
            if not icon.startswith("http"):
                icon = self._tv.tv_state.apps[self._tv.tv_state.current_app_id]["icon"]
            media_image_url = icon
        if media_image_url != self._media_image_url:
            self._media_image_url = media_image_url
            updated_data[MediaAttr.MEDIA_IMAGE_URL] = self._media_image_url

        _sound_output = self._sound_output
        self._sound_output = self._tv.tv_state.sound_output
        if _sound_output != self._sound_output:
            updated_data[MediaAttr.SOUND_MODE] = self.sound_output

        if updated_data:
            _LOG.debug("Updated data %s", updated_data)
            self.events.emit(Events.UPDATE, self.id, updated_data)

    async def _run_buffered_commands(self):
        # Handle awaiting commands to process
        # pylint: disable = R1702
        if self._buffered_callbacks:
            _LOG.debug("[%s] Connected, executing buffered commands", self._device_config.address)
            while self._buffered_callbacks:
                items = dict(sorted(self._buffered_callbacks.items()))
                try:
                    for timestamp, value in items.items():
                        del self._buffered_callbacks[timestamp]
                        if time.time() - timestamp <= BUFFER_LIFETIME:
                            _LOG.debug("[%s] Calling buffered command %s", self._device_config.address, value)
                            try:
                                if "kwargs" in value and len(value["kwargs"]) > 0:
                                    await value["function"](value["object"], *value["args"], **value["kwargs"])
                                elif "args" in value and len(value["args"]) > 0:
                                    await value["function"](value["object"], *value["args"])
                                else:
                                    await value["function"](value["object"])
                            # pylint: disable = W0718
                            except Exception as ex:
                                _LOG.warning(
                                    "[%s] Error while calling buffered command %s", self._device_config.address, ex
                                )
                        else:
                            _LOG.debug(
                                "[%s] Buffered command too old %s, dropping it", self._device_config.address, value
                            )
                except RuntimeError:
                    pass

    async def _connect_loop(self) -> None:
        """Connect loop.

        After sending magic packet we need to wait for the device to be accessible from network or maybe the
        device has shutdown by itself.
        """
        while True:
            try:
                await self.connect()
                if self._tv.tv_state.is_on:
                    _LOG.debug("[%s] LG TV connection succeeded", self._device_config.address)
                    self._connect_task = None
                    self._reconnect_retry = 0
                    self._retry_wakeonlan = False
                    break
            except WEBOSTV_EXCEPTIONS:
                pass
            self._reconnect_retry += 1
            self._attr_state = States.OFF
            if self._reconnect_retry > CONNECTION_RETRIES:
                _LOG.debug("[%s] LG not connected abort retries", self._device_config.address)
                self._connect_task = None
                self._reconnect_retry = 0
                break
            if self._retry_wakeonlan:
                self.wakeonlan()
            _LOG.debug(
                "[%s] LG not connected, retry %s / %s",
                self._device_config.address,
                self._reconnect_retry,
                CONNECTION_RETRIES,
            )
            await asyncio.sleep(DEFAULT_TIMEOUT)
        self._retry_wakeonlan = False

    async def connect(self):
        """Connect to the device."""
        # pylint: disable = R1702
        if self._connecting:  # TODO : to confirm or self.state != States.OFF:
            return
        try:
            await self._connect_lock.acquire()
            _LOG.debug("[%s] Connect", self._device_config.address)
            self._connecting = True
            self._tv: WebOsClient = WebOsClient(host=self._device_config.address, client_key=self._device_config.key)
            result: bool = await self._tv.connect()
            if result is None or self._tv.connection is None:
                _LOG.error(
                    "[%s] Connection process done but the connection is not available", self._device_config.address
                )
                raise WebOsTvCommandError("Connection process done but the connection is not available")

            _LOG.debug("[%s] Connection succeeded", self._device_config.address)
            await self._update_states(None)
            if not self._device_config.mac_address:
                await self._update_system()
            await self.register_websocket_events()
            self._available = True
            await self._run_buffered_commands()
        except WEBOSTV_EXCEPTIONS as ex:
            self._available = False
            _LOG.error("[%s] Unable to connect : %s", self._device_config.address, ex)
            if not self._connect_task:
                _LOG.warning(
                    "[%s] Unable to update, LG TV probably off: running connect task %s",
                    self._device_config.address,
                    ex,
                )
                self._connect_task = asyncio.create_task(self._connect_loop())
        finally:
            # Always emit connected event even if the device is unreachable (off)
            self.events.emit(Events.CONNECTED, self.id)
            self._connecting = False
            _LOG.debug("[%s] Connection task ends", self._device_config.address)
            self._connect_lock.release()

    async def reconnect(self):
        """Occurs when the TV has been turned off and on : the client has to be reset."""
        try:
            await self.connect()
        except WEBOSTV_EXCEPTIONS:
            pass

    async def _update_system(self) -> None:
        info = self._tv.tv_info
        self._model_name = info.system.get("modelName", "LG")
        self._serial_number = info.system.get("serialNumber")
        self._device_config.mac_address = info.software.get("device_id")

    async def disconnect(self):
        """Disconnect from TV."""
        _LOG.debug("[%s] Disconnect %s", self._device_config.address, self.id)
        try:
            await self._tv.disconnect()
            if self._connect_task:
                self._connect_task.cancel()
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.error("[%s] Unable to update: %s", self._device_config.address, ex)
            self._available = False
        finally:
            self._connect_task = None

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the device (serial number or mac address if none)."""
        return self._unique_id

    @property
    def attributes(self) -> dict[str, any]:
        """Return the device attributes."""
        updated_data = {
            MediaAttr.STATE: self.state,
            MediaAttr.MUTED: self.is_volume_muted,
            MediaAttr.VOLUME: self.volume_level,
            MediaAttr.MEDIA_TYPE: self._media_type,
            MediaAttr.MEDIA_IMAGE_URL: self.media_image_url,
            MediaAttr.MEDIA_TITLE: self.media_title,
            MediaAttr.SOUND_MODE_LIST: self.sound_outputs,
        }
        if self.source_list:
            updated_data[MediaAttr.SOURCE_LIST] = self.source_list
        if self.source:
            updated_data[MediaAttr.SOURCE] = self.source
        if self.sound_output:
            updated_data[MediaAttr.SOUND_MODE] = self.sound_output
        return updated_data

    @property
    def available(self) -> bool:
        """Return True if device is available."""
        return self._available

    @available.setter
    def available(self, value: bool):
        """Set device availability and emit CONNECTED / DISCONNECTED event on change."""
        if self._available != value:
            self._available = value
            # self.events.emit(Events.CONNECTED if value else Events.DISCONNECTED, self.id)

    @property
    def host(self) -> str:
        """Return the host of the device as string."""
        return self._tv.host

    @property
    def state(self) -> States:
        """Return the cached state of the device."""
        return self._attr_state

    @property
    def supported_features(self) -> list[Features]:
        """Return supported features."""
        return self._supported_features

    @property
    def source_list(self) -> list[str]:
        """Return a list of available input sources."""
        sources_list = sorted(
            [source_name for (source_name, source) in self._sources.items() if source[SOURCE_IS_APP] is False]
        )
        sources_list.extend(
            sorted([source_name for (source_name, source) in self._sources.items() if source[SOURCE_IS_APP] is True])
        )
        return sources_list

    @property
    def source(self) -> str:
        """Return the current input source."""
        return self._active_source

    @property
    def sound_output(self) -> str | None:
        """Return the current sound output."""
        if self._sound_output is None:
            return None
        _sound_output = LG_SOUND_OUTPUTS.get(self._sound_output, None)
        if _sound_output is None:
            _LOG.error(
                "[%s] Unknown sound output %s, report to developer", self._device_config.address, self._sound_output
            )
        return _sound_output

    @property
    def sound_outputs(self) -> [str]:
        """Return the current sound output."""
        return list(LG_SOUND_OUTPUTS.values())

    @property
    def is_volume_muted(self) -> bool:
        """Return boolean if volume is currently muted."""
        return self._attr_is_volume_muted

    @property
    def volume_level(self) -> float | None:
        """Volume level of the media player (0..100)."""
        return self._volume

    @property
    def media_image_url(self) -> str:
        """Image url of current playing media."""
        return self._media_image_url

    @property
    def media_title(self) -> str:
        """Title of current playing media."""
        return self._media_title

    @property
    def media_type(self) -> MediaType:
        """Current media type."""
        return self._media_type

    async def power_toggle(self) -> ucapi.StatusCodes:
        """Toggle power."""
        lg_state = await self.check_connect()
        _LOG.debug("[%s] Power toggle power state : %s", self._device_config.address, lg_state)
        if lg_state == LGState.ON:
            await self.power_off()
        else:
            await self.power_on()
        return ucapi.StatusCodes.OK

    def wakeonlan(self) -> None:
        """Send WOL command. to known mac addresses."""
        messages = []
        wol_port = self._device_config.wol_port
        if wol_port is None:
            wol_port = 9
        if self._device_config.mac_address is not None:
            _LOG.debug(
                "[%s] LG TV power on : sending magic packet to %s (wired)",
                self._device_config.address,
                self._device_config.mac_address,
            )
            messages.append(create_magic_packet(self._device_config.mac_address))

        if self._device_config.mac_address2 is not None:
            _LOG.debug(
                "[%s] LG TV power on : sending magic packet to %s (wifi)",
                self._device_config.address,
                self._device_config.mac_address2,
            )
            messages.append(create_magic_packet(self._device_config.mac_address2))

        if len(messages) > 0:
            broadcast = "<broadcast>"
            if self._device_config.broadcast is not None and self._device_config.broadcast != "255.255.255.255":
                broadcast = self._device_config.broadcast
            socket_instance = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            socket_instance.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            for msg in messages:
                socket_instance.sendto(msg, (broadcast, wol_port))
            socket_instance.close()

    async def check_connect(self) -> LGState:
        """Check power and connection state."""
        lg_state: LGState = LGState.ON
        # pylint: disable = W0718
        try:
            async with asyncio.timeout(5):
                state = await self._tv.get_power_state()
                state_value = state.get("state", None)
                if state_value is None or state_value == "Unknown":
                    if self._tv.tv_state.current_app_id in [None, ""]:
                        _LOG.debug("[%s] TV is already off [%s]", self._device_config.address, state)
                        lg_state = LGState.OFF
                elif state_value in ["Power Off", "Suspend", "Active Standby"]:
                    _LOG.debug("[%s] TV is in standby [%s]", self._device_config.address, state)
                    lg_state = LGState.STANDBY
        except Exception as ex:
            _LOG.debug("[%s] Could not get TV state, assuming off %s", self._device_config.address, ex)
            lg_state = LGState.OFF
        if lg_state == LGState.OFF:
            _LOG.debug("[%s] TV is not connected, calling connect", self._device_config.address)
            if not self._connect_task:
                _LOG.warning(
                    "[%s] Unable to update, LG TV probably off, running connect task", self._device_config.address
                )
                self._connect_task = asyncio.create_task(self._connect_loop())
        else:
            _LOG.debug("[%s] TV is connected", self._device_config.address)
        return lg_state

    async def power_on(self) -> ucapi.StatusCodes:
        """Send power-on command to LG TV."""
        # pylint: disable = W0718
        _LOG.debug("[%s] Power on", self._device_config.address)
        try:
            ip_address = self._device_config.broadcast
            if ip_address is None:
                ip_address = "255.255.255.255"
            _LOG.debug(
                "[%s] LG TV power on : sending magic packet to %s on interface %s, port %s, broadcast %s",
                self._device_config.address,
                self._device_config.mac_address,
                self._device_config.interface,
                self._device_config.wol_port,
                ip_address,
            )
            self.wakeonlan()
            self._retry_wakeonlan = True
            self._buffered_callbacks[time.time()] = {"object": self._tv, "function": WebOsClient.power_on}
            self.event_loop.create_task(self.check_connect())
            try:
                _LOG.debug(
                    "[%s] Sends power on command in case of TV is already connected", self._device_config.address
                )
                await self._tv.power_on()
            except Exception as ex:
                _LOG.error("[%s] LG TV error power on command %s", self._device_config.address, ex)
            return ucapi.StatusCodes.OK
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.error("[%s] LG TV error power_on %s", self._device_config.address, ex)
        except Exception as ex:
            _LOG.error("[%s] LG TV error power_on %s", self._device_config.address, ex)
        # return ucapi.StatusCodes.BAD_REQUEST
        return ucapi.StatusCodes.OK

    async def power_off_deferred(self):
        """Power off deferred."""
        # Sleep time : sometimes the connection variable is not defined although the lib reports the TV as connected
        if self._tv.connection is None:
            await asyncio.sleep(2)
        await self._tv.command("request", endpoints.POWER_OFF)
        self._attr_state = States.OFF

    @retry()
    async def power_off(self) -> ucapi.StatusCodes:
        """Send power-off command to LG TV."""
        _LOG.debug("[%s] Power off", self._device_config.address)
        self._retry_wakeonlan = False
        lg_state = await self.check_connect()
        if lg_state == LGState.ON:
            _LOG.debug("[%s] TV is ON, powering off [%s]", self._device_config.address, lg_state)
            await self._tv.command("request", endpoints.POWER_OFF)
            self._attr_state = States.OFF
        else:
            _LOG.debug(
                "[%s] Power off command : TV seems to be off, adding power_off call to buffered commands if "
                "connection is reestablished",
                self._device_config.address,
            )
            self._buffered_callbacks[time.time()] = {"object": self, "function": LGDevice.power_off_deferred}
        return ucapi.StatusCodes.OK

    @retry()
    async def set_volume_level(self, volume: float | None) -> ucapi.StatusCodes:
        """Set volume level, range 0..100."""
        if volume is None:
            return ucapi.StatusCodes.BAD_REQUEST
        _LOG.debug("[%s] LG TV setting volume to %s", self._device_config.address, volume)
        await self._tv.set_volume(int(round(volume)))
        self.events.emit(Events.UPDATE, self.id, {MediaAttr.VOLUME: volume})
        return ucapi.StatusCodes.OK

    @retry()
    async def volume_up(self) -> ucapi.StatusCodes:
        """Send volume-up command to LG TV."""
        await self._tv.volume_up()
        return ucapi.StatusCodes.OK

    @retry()
    async def volume_down(self) -> ucapi.StatusCodes:
        """Send volume-down command to LG TV."""
        await self._tv.volume_down()
        return ucapi.StatusCodes.OK

    @retry()
    async def mute(self, muted: bool) -> ucapi.StatusCodes:
        """Send mute command to LG TV."""
        _LOG.debug("[%s] Sending mute: %s", self._device_config.address, muted)
        await self._tv.set_mute(muted)
        return ucapi.StatusCodes.OK

    @retry()
    async def async_media_play(self) -> ucapi.StatusCodes:
        """Send play command."""
        self._paused = False
        await self._tv.play()
        return ucapi.StatusCodes.OK

    @retry()
    async def async_media_pause(self) -> ucapi.StatusCodes:
        """Send media pause command to media player."""
        self._paused = True
        await self._tv.pause()
        return ucapi.StatusCodes.OK

    @retry()
    async def play_pause(self) -> ucapi.StatusCodes:
        """Send toggle-play-pause command to LG TV."""
        if self._paused:
            await self.async_media_play()
        else:
            await self.async_media_pause()
        return ucapi.StatusCodes.OK

    @retry()
    async def stop(self) -> ucapi.StatusCodes:
        """Send toggle-play-pause command to LG TV."""
        await self._tv.stop()
        return ucapi.StatusCodes.OK

    @retry()
    async def next(self) -> ucapi.StatusCodes:
        """Send next-track command to LG TV."""
        if self._tv.tv_state.current_app_id == LIVE_TV_APP_ID:
            await self._tv.channel_up()
        else:
            await self._tv.fast_forward()
        return ucapi.StatusCodes.OK

    @retry()
    async def previous(self) -> ucapi.StatusCodes:
        """Send previous-track command to LG TV."""
        if self._tv.tv_state.current_app_id == LIVE_TV_APP_ID:
            await self._tv.channel_down()
        else:
            await self._tv.rewind()
        return ucapi.StatusCodes.OK

    async def select_source_deferred(self, source: str | None, delay: int = 0) -> ucapi.StatusCodes:
        """Send input_source command to LG TV."""
        if not source:
            return ucapi.StatusCodes.BAD_REQUEST
        _LOG.debug("[%s] LG TV set input: %s", self._device_config.address, source)
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            if not self._tv.tv_state.is_on:
                raise WebOsTvCommandError
            # If sources is empty, device is not connected so raise error to trigger connection
            if not self._sources:
                raise WebOsTvCommandError
            if (source_dict := self._sources.get(source)) is None:
                _LOG.warning("[%s] Source %s not found for %s", self._device_config.address, source, self._sources)
                return ucapi.StatusCodes.BAD_REQUEST
            if source_dict.get("title"):
                await self._tv.launch_app(source_dict["id"])
            elif source_dict.get("label"):
                await self._tv.set_input(source_dict["id"])
            _LOG.debug("[%s] LG TV set input: %s succeeded", self._device_config.address, source)
            return ucapi.StatusCodes.OK
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.error("[%s] LG TV error select_source %s", self._device_config.address, ex)
        # pylint: disable = W0718
        except Exception as ex:
            _LOG.error("[%s] LG TV unknown error select_source %s", self._device_config.address, ex)
        return ucapi.StatusCodes.BAD_REQUEST

    async def select_source_next(self) -> ucapi.StatusCodes:
        """Switch to next source."""
        if self._tv is None:
            return ucapi.StatusCodes.SERVICE_UNAVAILABLE
        sources: list[dict] = list(self._tv.tv_state.inputs.values())
        current_source = self.source
        if not sources or len(sources) == 0:
            _LOG.error("[%s] LG TV next input command : sources list is not feed yet", self._device_config.address)
            return ucapi.StatusCodes.SERVICE_UNAVAILABLE
        if not current_source:
            current_source = sources[0]["id"]
        else:
            try:
                source = [source for source in sources if source["id"] == current_source]
                if len(source) > 0:
                    source = source[0]
                else:
                    source = None
                index = sources.index(source)
                index += 1
                if index >= len(sources):
                    index = 0
                current_source = sources[index]["id"]
            except (ValueError, AttributeError):
                current_source = sources[0]["id"]
        return await self.select_source(current_source)

    async def select_source(self, source: str | None, delay: int = 0) -> ucapi.StatusCodes:
        """Send input_source command to LG TV."""
        if not source:
            return ucapi.StatusCodes.BAD_REQUEST
        _LOG.debug("[%s] LG TV set input: %s", self._device_config.address, source)
        launch_app = False
        try:
            res = await self.select_source_deferred(source, delay)
            if res != ucapi.StatusCodes.OK:
                raise WebOsTvCommandError
            return res
        except WebOsTvCommandError:
            await self.power_on()
            if launch_app:
                self._buffered_callbacks[time.time()] = {
                    "object": self,
                    "function": LGDevice.select_source_deferred,
                    "args": [source, INIT_APPS_LAUNCH_DELAY],
                }
            else:
                self._buffered_callbacks[time.time()] = {
                    "object": self,
                    "function": LGDevice.select_source_deferred,
                    "args": [source, 0],
                }
            _LOG.info(
                "[%s] Device is not ready to accept command, buffering it : %s",
                self._device_config.address,
                self._buffered_callbacks,
            )
            self.event_loop.create_task(self.reconnect())
            return ucapi.StatusCodes.OK
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.error("[%s] LG TV error select_source %s", self._device_config.address, ex)
        # pylint: disable = W0718
        except Exception as ex:
            _LOG.error("[%s] LG TV unknown error select_source %s", self._device_config.address, ex)
        return ucapi.StatusCodes.BAD_REQUEST

    async def select_sound_output_deferred(self, sound_output: str | None) -> ucapi.StatusCodes:
        """Set sound output."""
        _LOG.debug("[%s] LG set sound output to %s", self._device_config.address, sound_output)
        await self._tv.change_sound_output(sound_output)
        return ucapi.StatusCodes.OK

    async def select_sound_output(self, mode: str | None) -> ucapi.StatusCodes:
        """Set sound output."""
        if mode is None:
            return ucapi.StatusCodes.BAD_REQUEST
        _LOG.debug("[%s] LG TV setting sound output to %s", self._device_config.address, mode)
        inv_map = {v: k for k, v in LG_SOUND_OUTPUTS.items()}
        sound_output = inv_map.get(mode)
        if sound_output is None:
            _LOG.debug("[%s] LG TV invalid sound output %s from list (%s)", self._device_config.address, mode, inv_map)
            return ucapi.StatusCodes.BAD_REQUEST
        try:
            res = await self.select_sound_output_deferred(sound_output)
            if res != ucapi.StatusCodes.OK:
                raise WebOsTvCommandError
            return res
        except WebOsTvCommandError:
            await self.power_on()
            self._buffered_callbacks[time.time()] = {
                "object": self,
                "function": LGDevice.select_sound_output_deferred,
                "args": [sound_output],
            }
            _LOG.info(
                "[%s] Device is not ready to accept command, buffering it : %s",
                self._device_config.address,
                self._buffered_callbacks,
            )
            self.event_loop.create_task(self.reconnect())
            return ucapi.StatusCodes.OK
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.error("[%s] LG TV error select_sound_output %s", self._device_config.address, ex)
        # pylint: disable = W0718
        except Exception as ex:
            _LOG.error("[%s] LG TV unknown error select_sound_output %s", self._device_config.address, ex)
        return ucapi.StatusCodes.BAD_REQUEST

    @retry()
    async def button(self, button: str) -> ucapi.StatusCodes:
        """Send a button command."""
        await self._tv.button(button)
        return ucapi.StatusCodes.OK

    @retry()
    async def turn_screen_off(self, webos_ver="") -> ucapi.StatusCodes:
        """Turn TV Screen off."""
        epname = f"TURN_OFF_SCREEN_WO{webos_ver}" if webos_ver else "TURN_OFF_SCREEN"
        endpoint = getattr(endpoints, epname, None)
        if endpoint is None:
            endpoint = LG_ADDITIONAL_ENDPOINTS.get(epname, None)

        if endpoint is None:
            raise ValueError(f"there's no {epname} endpoint")

        await self._tv.request(endpoint, {"standbyMode": "active"})
        return ucapi.StatusCodes.OK

    @retry()
    async def turn_screen_on(self, webos_ver="") -> ucapi.StatusCodes:
        """Turn TV Screen on."""
        epname = f"TURN_ON_SCREEN_WO{webos_ver}" if webos_ver else "TURN_ON_SCREEN"
        endpoint = getattr(endpoints, epname, None)
        if endpoint is None:
            endpoint = LG_ADDITIONAL_ENDPOINTS.get(epname, None)

        if endpoint is None:
            raise ValueError(f"there's no {epname} endpoint")

        await self._tv.request(endpoint, {"standbyMode": "active"})
        return ucapi.StatusCodes.OK
