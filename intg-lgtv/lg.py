"""
This module implements the AVR AVR receiver communication of the Remote Two integration driver.

:copyright: (c) 2023 by Unfolded Circle ApS.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import asyncio
import logging
import socket
import struct
import time
from asyncio import AbstractEventLoop, Lock
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
from xmlrpc.client import ProtocolError

import ucapi
from aiohttp import ServerTimeoutError
from aiowebostv import WebOsClient, WebOsTvCommandError, endpoints
from config import LGConfigDevice
from const import LG_FEATURES, LIVE_TV_APP_ID, WEBOSTV_EXCEPTIONS, LG_SOUND_OUTPUTS
from httpx import TransportError
from pyee.asyncio import AsyncIOEventEmitter
from ucapi.media_player import Attributes as MediaAttr, States
from ucapi.media_player import Features, MediaType

_LOG = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 5
BUFFER_LIFETIME = 30
CONNECTION_RETRIES = 10

INIT_APPS_LAUNCH_DELAY = 10


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


def cmd_wrapper(
        func: Callable[Concatenate[_LGDeviceT, _P], Awaitable[ucapi.StatusCodes | None]],
) -> Callable[Concatenate[_LGDeviceT, _P], Coroutine[Any, Any, ucapi.StatusCodes | None]]:
    """Catch command exceptions."""

    @wraps(func)
    async def wrapper(obj: _LGDeviceT, *args: _P.args, **kwargs: _P.kwargs) -> ucapi.StatusCodes:
        """Wrap all command methods."""
        try:
            await func(obj, *args, **kwargs)
            return ucapi.StatusCodes.OK
        except WEBOSTV_EXCEPTIONS as exc:
            # If TV is off, we expect calls to fail.
            if obj.state == States.OFF:
                log_function = _LOG.debug
            else:
                log_function = _LOG.error
            log_function(
                "Error calling %s on entity %s: %r trying to reconnect and send the command next",
                func.__name__,
                obj.id,
                exc,
            )
            # Kodi not connected, launch a connect task but
            # don't wait more than 5 seconds, then process the command if connected
            # else returns error
            connect_task = obj.event_loop.create_task(obj.connect())
            await asyncio.sleep(0)
            try:
                async with asyncio.timeout(5):
                    await connect_task
            except asyncio.TimeoutError:
                log_function("Timeout for reconnect, command won't be sent")
            else:
                if obj.available:
                    try:
                        log_function("Trying again command %s : %r", func.__name__, obj.id)
                        await func(obj, *args, **kwargs)
                        return ucapi.StatusCodes.OK
                    except (TransportError, ProtocolError, ServerTimeoutError) as ex:
                        log_function(
                            "Error calling %s on entity %s: %r trying to reconnect",
                            func.__name__,
                            obj.id,
                            ex,
                        )
            # If TV is off, we expect calls to fail.
            # await obj.event_loop.create_task(obj.connect())
            return ucapi.StatusCodes.BAD_REQUEST
        # pylint: disable = W0718
        except Exception:
            _LOG.error("Unknown error %s", func.__name__)

    return wrapper


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
        self._attr_available: bool = True
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

        _LOG.debug("LG TV created: %s", device_config.address)

    def update_config(self, device_config: LGConfigDevice):
        self._device_config = device_config

    async def async_activate_websocket(self):
        """Activate websocket for listening if wanted. the websocket has to be recreated when the device goes off."""
        _LOG.info("LG TV Activating websocket connection")

        async def _on_state_changed(client: WebOsClient):
            """State changed callback."""
            await self._update_states(client)
            if not client.power_state:
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
            _LOG.debug(f"Sound output: {client.sound_output}")

        await self._tv.register_state_update_callback(_on_state_changed)
        await self._tv.subscribe_sound_output(_on_state_changed)

    def _update_sources(self, updated_data: any) -> None:
        """Update list of sources from current source, apps, inputs and configured list."""
        current_source_list = self._sources
        self._sources = {}
        active_source = None
        found_live_tv = False
        for app in self._tv.apps.values():
            if app["id"] == LIVE_TV_APP_ID:
                found_live_tv = True
            if app["id"] == self._tv.current_app_id:
                active_source = app["title"]
                self._sources[app["title"]] = app
            else:
                self._sources[app["title"]] = app

        for source in self._tv.inputs.values():
            if source["appId"] == LIVE_TV_APP_ID:
                found_live_tv = True
            if source["appId"] == self._tv.current_app_id:
                active_source = source["id"]
                self._sources[source["id"]] = source
            else:
                self._sources[source["id"]] = source

        # empty list, TV may be off, keep previous list
        if not self._sources and current_source_list:
            self._sources = current_source_list
        # special handling of live tv since this might
        # not appear in the app or input lists in some cases
        elif not found_live_tv:
            app = {"id": LIVE_TV_APP_ID, "title": "Live TV"}
            if self._tv.current_app_id == LIVE_TV_APP_ID:
                active_source = app["title"]
                self._sources["Live TV"] = app
            else:
                self._sources["Live TV"] = app

        if (
                not current_source_list and self._sources
        ):  # or (self._sources and list(self._sources.keys()).sort() != list(current_source_list).sort()):
            _LOG.debug("Source list %s", self._sources)
            updated_data[MediaAttr.SOURCE_LIST] = sorted(self._sources)

        if active_source != self._active_source:
            _LOG.debug("Active source %s", active_source)
            self._active_source = active_source
            updated_data[MediaAttr.SOURCE] = self._active_source

    async def _update_states(self, data: WebOsClient | None) -> None:
        """Update entity state attributes."""
        # pylint: disable = R0915
        updated_data = {}
        if not self._sources:
            try:
                sources = await self._tv.get_inputs()
                _LOG.info("Empty sources, retrieve them %s", sources)
                await self._tv.set_inputs_state(sources)
                await self._tv.set_apps_state(await self._tv.get_apps())
                await self._tv.set_current_app_state(await self._tv.get_current_app())
            # pylint: disable = W0718
            except Exception:
                pass

        self._update_sources(updated_data)

        # Bug on LG library where power_state not updated, force it
        try:
            # pylint: disable = W0212
            self._tv._power_state = await self._tv.get_power_state()
            is_on = self._tv.is_on
        # pylint: disable = W0718
        except Exception:
            is_on = False

        if data and data.sound_output:
            if self._sound_output != data.sound_output:
                self._sound_output = data.sound_output
                updated_data[MediaAttr.SOUND_MODE] = self.sound_output
        elif self._sound_output is None:
            try:
                self._sound_output = await self._tv.get_sound_output()
                if self._sound_output:
                    updated_data[MediaAttr.SOUND_MODE] = self.sound_output
                _LOG.debug("Sound output %s", self._sound_output)
            except Exception as ex:
                _LOG.warning("Error extraction of sound output", ex)
                pass

        state = States.ON if is_on else States.OFF
        if state != self.state:
            self._attr_state = state
            updated_data[MediaAttr.STATE] = self.state

        muted = cast(bool, self._tv.muted)
        if muted != self._attr_is_volume_muted:
            self._attr_is_volume_muted = muted
            updated_data[MediaAttr.MUTED] = self._attr_is_volume_muted

        if self._tv.volume is not None:
            volume = cast(float, self._tv.volume)
            if volume != self._volume:
                self._volume = volume
                updated_data[MediaAttr.VOLUME] = self._volume

        media_type = MediaType.VIDEO
        if self._tv.current_app_id == LIVE_TV_APP_ID:
            media_type = MediaType.TVSHOW

        if media_type != self._media_type:
            self._media_type = media_type
            updated_data[MediaAttr.MEDIA_TYPE] = self._media_type

        media_title = ""
        if self._tv.current_app_id == LIVE_TV_APP_ID and self._tv.current_channel is not None:
            media_title = cast(str, self._tv.current_channel.get("channelName"))

        if media_title != self._media_title:
            self._media_title = media_title
            updated_data[MediaAttr.MEDIA_TITLE] = self._media_title

        # TODO playing / paused state to update
        media_image_url = ""
        if self._tv.current_app_id in self._tv.apps:
            icon: str = self._tv.apps[self._tv.current_app_id]["largeIcon"]
            if not icon.startswith("http"):
                icon = self._tv.apps[self._tv.current_app_id]["icon"]
            media_image_url = icon
        if media_image_url != self._media_image_url:
            self._media_image_url = media_image_url
            updated_data[MediaAttr.MEDIA_IMAGE_URL] = self._media_image_url

        if updated_data:
            self.events.emit(Events.UPDATE, self.id, updated_data)

        _sound_output = self._sound_output
        self._sound_output = self._tv.sound_output
        if _sound_output != self._sound_output:
            updated_data[MediaAttr.SOUND_MODE] = self.sound_output

    async def _connect_loop(self) -> None:
        """Connect loop.

        After sending magic packet we need to wait for the device to be accessible from network or maybe the
        device has shutdown by itself.
        """
        while True:
            await asyncio.sleep(DEFAULT_TIMEOUT)
            try:
                await self.connect()
                if self._tv.is_on:
                    _LOG.debug("LG TV connection succeeded")
                    self._connect_task = None
                    self._reconnect_retry = 0
                    break
            except WEBOSTV_EXCEPTIONS:
                pass
            self._reconnect_retry += 1
            if self._reconnect_retry > CONNECTION_RETRIES:
                _LOG.debug("LG %s not connected abort retries", self._device_config.address)
                self._connect_task = None
                self._reconnect_retry = 0
                break
            _LOG.debug(
                "LG %s not connected, retry %s / %s",
                self._device_config.address,
                self._reconnect_retry,
                CONNECTION_RETRIES,
            )

    async def connect(self):
        """Connect to the device."""
        # pylint: disable = R1702
        if self._connecting:  # TODO : to confirm or self.state != States.OFF:
            return
        try:
            await self._connect_lock.acquire()
            # _LOG.debug("Connect %s", self._device_config.address)
            self._connecting = True
            self._tv: WebOsClient = WebOsClient(host=self._device_config.address, client_key=self._device_config.key)
            await self._tv.connect()
            await self._update_states(None)
            if not self._device_config.mac_address:
                await self._update_system()
            await self.async_activate_websocket()
            self._attr_available = True
            # Handle awaiting commands to process
            if self._buffered_callbacks:
                while self._buffered_callbacks:
                    try:
                        items = self._buffered_callbacks.copy()
                        for timestamp, value in items.items():
                            if time.time() - timestamp <= BUFFER_LIFETIME:
                                _LOG.debug("Calling buffered command %s", value)
                                try:
                                    await value["function"](*value["args"])
                                    del self._buffered_callbacks[timestamp]
                                # pylint: disable = W0718
                                except Exception:
                                    pass
                            else:
                                _LOG.debug("Buffered command too old %s, dropping it", value)
                        self._buffered_callbacks.clear()
                    except RuntimeError:
                        pass
        except WEBOSTV_EXCEPTIONS as ex:
            self._attr_available = False
            if not self._connect_task:
                _LOG.warning("Unable to update, LG TV probably off: %s, running connect task", ex)
                self._connect_task = asyncio.create_task(self._connect_loop())
        finally:
            # Always emit connected event even if the device is unreachable (off)
            self.events.emit(Events.CONNECTED, self.id)
            self._connecting = False
            self._connect_lock.release()

    async def reconnect(self):
        """Occurs when the TV has been turned off and on : the client has to be reset."""
        try:
            await self.connect()
        except WEBOSTV_EXCEPTIONS:
            pass

    async def _update_system(self) -> None:
        info = await self._tv.get_system_info()
        self._model_name = info.get("modelName")
        self._serial_number = info.get("serialNumber")
        info = await self._tv.get_software_info()
        self._device_config.mac_address = info.get("device_id")

    async def disconnect(self):
        """Disconnect from TV."""
        _LOG.debug("Disconnect %s", self.id)
        try:
            await self._tv.disconnect()
            if self._connect_task:
                self._connect_task.cancel()
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.error("Unable to update: %s", ex)
            self._attr_available = False
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
        return self._attr_available

    @available.setter
    def available(self, value: bool):
        """Set device availability and emit CONNECTED / DISCONNECTED event on change."""
        if self._attr_available != value:
            self._attr_available = value
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
        return sorted(self._sources)

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
            _LOG.error("Unknown sound output %s, report to developer", self._sound_output)
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
        is_off = False
        state = None
        try:
            async with asyncio.timeout(5):
                state = await self._tv.get_power_state()
                state_value = state.get("state", None)
                if state_value == "Unknown":
                    # fallback to current app id for some older webos versions
                    # which don't support explicit power state
                    if self._tv.current_app_id in [None, ""]:
                        _LOG.debug("TV is already off [%s]", state)
                        is_off = True
                elif state_value in [None, "Power Off", "Suspend", "Active Standby"]:
                    _LOG.debug("TV is already off [%s]", state)
                    is_off = True
        except Exception:
            pass
        if is_off:
            await self.power_on()
        else:
            await self.power_off()
        return ucapi.StatusCodes.OK

    def wakeonlan(self) -> None:
        """Send WOL command. to known mac addresses."""
        messages = []
        if self._device_config.mac_address:
            _LOG.debug("LG TV power on : sending magic packet to %s (wired)",
                       self._device_config.mac_address)
            messages.append(create_magic_packet(self._device_config.mac_address))

        if self._device_config.mac_address2:
            _LOG.debug("LG TV power on : sending magic packet to %s (wifi)",
                       self._device_config.mac_address2)
            messages.append(create_magic_packet(self._device_config.mac_address2))

        if len(messages) > 0:
            broadcast = "<broadcast>"
            if self._device_config.broadcast is not None and self._device_config.broadcast != "255.255.255.255":
                broadcast = self._device_config.broadcast
            socket_instance = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            socket_instance.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            for msg in messages:
                socket_instance.sendto(msg, (broadcast, self._device_config.wol_port))
            socket_instance.close()

    async def power_on(self) -> ucapi.StatusCodes:
        """Send power-on command to LG TV."""
        try:
            ip_address = self._device_config.broadcast
            if ip_address is None:
                ip_address = "255.255.255.255"
            _LOG.debug(
                "LG TV power on : sending magic packet to %s on interface %s, port %s, broadcast %s",
                self._device_config.mac_address,
                self._device_config.interface,
                self._device_config.wol_port,
                ip_address
            )

            self.wakeonlan()
            return ucapi.StatusCodes.OK
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.error("LG TV error power_on %s", ex)
        # pylint: disable = W0718
        except Exception as ex:
            _LOG.error("LG TV error power_on %s", ex)
        # return ucapi.StatusCodes.BAD_REQUEST
        return ucapi.StatusCodes.OK

    @cmd_wrapper
    async def power_off(self):
        """Send power-off command to LG TV."""
        is_off = False
        state = None
        try:
            async with asyncio.timeout(5):
                state = await self._tv.get_power_state()
                state_value = state.get("state", None)
                if state_value == "Unknown":
                    # fallback to current app id for some older webos versions
                    # which don't support explicit power state
                    if self._tv.current_app_id in [None, ""]:
                        _LOG.debug("TV is already off [%s]", state)
                        is_off = True
                elif state_value in [None, "Power Off", "Suspend", "Active Standby"]:
                    _LOG.debug("TV is already off [%s]", state)
                    is_off = True
        except asyncio.TimeoutError:
            _LOG.debug("Power off requested but could not get TV state")
            is_off = True
        if is_off is False:
            _LOG.debug("TV is ON, powering off [%s]", state)
            await self._tv.command("request", endpoints.POWER_OFF)

    @cmd_wrapper
    async def set_volume_level(self, volume: float | None):
        """Set volume level, range 0..100."""
        if volume is None:
            return ucapi.StatusCodes.BAD_REQUEST
        _LOG.debug("LG TV setting volume to %s", volume)
        await self._tv.set_volume(int(round(volume)))
        self.events.emit(Events.UPDATE, self.id, {MediaAttr.VOLUME: volume})

    @cmd_wrapper
    async def volume_up(self):
        """Send volume-up command to LG TV."""
        await self._tv.volume_up()

    @cmd_wrapper
    async def volume_down(self):
        """Send volume-down command to LG TV."""
        await self._tv.volume_down()

    @cmd_wrapper
    async def mute(self, muted: bool):
        """Send mute command to LG TV."""
        _LOG.debug("Sending mute: %s", muted)
        await self._tv.set_mute(muted)

    @cmd_wrapper
    async def async_media_play(self) -> None:
        """Send play command."""
        self._paused = False
        await self._tv.play()

    @cmd_wrapper
    async def async_media_pause(self) -> None:
        """Send media pause command to media player."""
        self._paused = True
        await self._tv.pause()

    @cmd_wrapper
    async def play_pause(self):
        """Send toggle-play-pause command to LG TV."""
        if self._paused:
            await self.async_media_play()
        else:
            await self.async_media_pause()

    @cmd_wrapper
    async def stop(self):
        """Send toggle-play-pause command to LG TV."""
        await self._tv.stop()

    @cmd_wrapper
    async def next(self):
        """Send next-track command to LG TV."""
        if self._tv.current_app_id == LIVE_TV_APP_ID:
            await self._tv.channel_up()
        else:
            await self._tv.fast_forward()

    @cmd_wrapper
    async def previous(self):
        """Send previous-track command to LG TV."""
        if self._tv.current_app_id == LIVE_TV_APP_ID:
            await self._tv.channel_down()
        else:
            await self._tv.rewind()

    async def select_source_deferred(self, source: str | None, delay: int = 0) -> ucapi.StatusCodes:
        """Send input_source command to LG TV."""
        if not source:
            return ucapi.StatusCodes.BAD_REQUEST
        _LOG.debug("LG TV set input: %s", source)
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            if not self._tv.is_on:
                raise WebOsTvCommandError
            # If sources is empty, device is not connected so raise error to trigger connection
            if not self._sources:
                raise WebOsTvCommandError
            if (source_dict := self._sources.get(source)) is None:
                _LOG.warning("Source %s not found for %s", source, self._sources)
                return ucapi.StatusCodes.BAD_REQUEST
            if source_dict.get("title"):
                await self._tv.launch_app(source_dict["id"])
            elif source_dict.get("label"):
                await self._tv.set_input(source_dict["id"])
            _LOG.debug("LG TV set input: %s succeeded", source)
            return ucapi.StatusCodes.OK
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.error("LG TV error select_source", ex)
        # pylint: disable = W0718
        except Exception as ex:
            _LOG.error("LG TV unknown error select_source %s", ex)
        return ucapi.StatusCodes.BAD_REQUEST

    async def select_source_next(self) -> ucapi.StatusCodes:
        if self._tv is None:
            return ucapi.StatusCodes.SERVICE_UNAVAILABLE
        sources:list[dict] = list(self._tv.inputs.values())
        current_source = self.source
        if not sources or len(sources) == 0:
            _LOG.error("LG TV next input command : sources list is not feed yet")
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
        _LOG.debug("LG TV set input: %s", source)
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
                    "function": self.select_source_deferred,
                    "args": [source, INIT_APPS_LAUNCH_DELAY],
                }
            else:
                self._buffered_callbacks[time.time()] = {
                    "function": self.select_source_deferred,
                    "args": [source],
                }
            _LOG.info(
                "Device is not ready to accept command, buffering it : %s",
                self._buffered_callbacks,
            )
            self.event_loop.create_task(self.reconnect())
            return ucapi.StatusCodes.OK
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.error("LG TV error select_source %s", ex)
        # pylint: disable = W0718
        except Exception as ex:
            _LOG.error("LG TV unknown error select_source %s", ex)
        return ucapi.StatusCodes.BAD_REQUEST

    async def select_sound_output_deferred(self, sound_output: str | None) -> ucapi.StatusCodes:
        """Set sound output."""
        _LOG.debug("LG set sound output to %s", sound_output)
        await self._tv.change_sound_output(sound_output)
        return ucapi.StatusCodes.OK

    async def select_sound_output(self, mode: str | None) -> ucapi.StatusCodes:
        """Set sound output."""
        if mode is None:
            return ucapi.StatusCodes.BAD_REQUEST
        _LOG.debug("LG TV setting sound output to %s", mode)
        inv_map = {v: k for k, v in LG_SOUND_OUTPUTS.items()}
        sound_output = inv_map.get(mode)
        if sound_output is None:
            _LOG.debug("LG TV invalid sound output %s from list (%s)", mode, inv_map)
            return ucapi.StatusCodes.BAD_REQUEST
        try:
            res = await self.select_sound_output_deferred(sound_output)
            if res != ucapi.StatusCodes.OK:
                raise WebOsTvCommandError
            return res
        except WebOsTvCommandError:
            await self.power_on()
            self._buffered_callbacks[time.time()] = {
                "function": self.select_sound_output_deferred,
                "args": [sound_output],
            }
            _LOG.info(
                "Device is not ready to accept command, buffering it : %s",
                self._buffered_callbacks,
            )
            self.event_loop.create_task(self.reconnect())
            return ucapi.StatusCodes.OK
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.error("LG TV error select_sound_output %s", ex)
        # pylint: disable = W0718
        except Exception as ex:
            _LOG.error("LG TV unknown error select_sound_output %s", ex)
        return ucapi.StatusCodes.BAD_REQUEST

    @cmd_wrapper
    async def button(self, button: str):
        """Send a button command."""
        await self._tv.button(button)
