"""
This module implements the AVR AVR receiver communication of the Remote Two integration driver.

:copyright: (c) 2023 by Unfolded Circle ApS.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import logging
import os
from asyncio import AbstractEventLoop
from enum import IntEnum
from typing import cast

import ucapi
from aiowebostv.buttons import BUTTONS

from config import LGConfigDevice
from pyee import AsyncIOEventEmitter
from ucapi.media_player import Attributes as MediaAttr, MediaType, States as MediaStates
from aiowebostv import WebOsClient
from const import *
from wakeonlan import send_magic_packet

_LOG = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 5

class Events(IntEnum):
    """Internal driver events."""

    CONNECTING = 0
    CONNECTED = 1
    DISCONNECTED = 2
    ERROR = 3
    UPDATE = 4
    # IP_ADDRESS_CHANGED = 6


class States(IntEnum):
    """State of a connected AVR."""

    UNKNOWN = 0
    UNAVAILABLE = 1
    OFF = 2
    ON = 3
    PLAYING = 4
    PAUSED = 5
    STOPPED = 6


LG_STATE_MAPPING = {
    States.OFF : MediaStates.OFF,
    States.ON : MediaStates.ON,
    States.STOPPED : MediaStates.STANDBY,
    States.PLAYING : MediaStates.PLAYING,
    States.PAUSED : MediaStates.PAUSED,
}


class LGDevice:
    """Representing a LG TV Device."""

    def __init__(
        self,
        device_config: LGConfigDevice,
        timeout: float = DEFAULT_TIMEOUT,
        loop: AbstractEventLoop | None = None,
    ):
        """Create instance with given IP or hostname of AVR."""
        # identifier from configuration
        self._connecting = False
        self._device_config = device_config # For reconnection
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
        self._mac_address = self.id
        self._connect_task = None

        _LOG.debug("LG TV created: %s", device_config.address)

    async def async_activate_websocket(self):
        """Activate websocket for listening if wanted.
        the websocket has to be recreated when the device goes off"""
        _LOG.info("LG TV Activating websocket connection")

        async def _on_state_changed(client):
            """State changed callback."""
            await self._update_states()
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
            # _LOG.debug(f"Sound output: {client.sound_output}")

        await self._tv.register_state_update_callback(_on_state_changed)

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

        for source in self._tv.inputs.values():
            if source["appId"] == LIVE_TV_APP_ID:
                found_live_tv = True
            if source["appId"] == self._tv.current_app_id:
                active_source = source["label"]
                self._sources[source["label"]] = source

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

        if not current_source_list or (self._sources and list(self._sources.keys()).sort() != list(current_source_list).sort()):
            updated_data[MediaAttr.SOURCE_LIST] = sorted(current_source_list)

        if active_source != self._active_source:
            self._active_source = active_source
            updated_data[MediaAttr.SOURCE] = self._active_source

    def is_on(self):
        """Return true if TV is powered on."""
        state = self._power_state.get("state")
        if state == "Unknown":
            # fallback to current app id for some older webos versions
            # which don't support explicit power state
            if self._current_app_id in [None, ""]:
                return False
            return True
        if state in [None, "Power Off", "Suspend", "Active Standby"]:
            return False
        return True

    async def _update_states(self) -> None:
        """Update entity state attributes."""
        updated_data = {}
        self._update_sources(updated_data)

        # Bug on LG library where power_state not updated, force it
        try:
            self._tv._power_state = await self._tv.get_power_state()
            is_on = self._tv.is_on
        except Exception:
            is_on = False

        state = (
            States.ON if is_on else States.OFF
        )
        if state != self.state:
            self._attr_state = state
            updated_data[MediaAttr.STATE] = LG_STATE_MAPPING.get(self.state)

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
        if (self._tv.current_app_id == LIVE_TV_APP_ID) and (
            self._tv.current_channel is not None
        ):
            media_title = cast(
                str, self._tv.current_channel.get("channelName")
            )

        if media_title != self._media_title:
            self._media_title = media_title
            updated_data[MediaAttr.MEDIA_TITLE] = self._media_title

        #TODO playing / paused state to update
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


        # if self.state != States.OFF or not self._supported_features:
        #     self._supported_features = LG_FEATURES
        #     if self._tv.sound_output in ("external_arc", "external_speaker"):
        #         self._supported_features.append(Features.VOLUME_UP_DOWN)
        #     elif self._tv.sound_output != "lineout":
        #         self._supported_features.append(Features.VOLUME_UP_DOWN)
        #         self._supported_features.append(Features.VOLUME)

        # if self._tv.system_info is not None or self.state != States.OFF:
        #     maj_v = self._tv.software_info.get("major_ver")
        #     min_v = self._tv.software_info.get("minor_ver")
        #     if maj_v and min_v:
        #         self._attr_device_info["sw_version"] = f"{maj_v}.{min_v}"
        #
        #     if model := self._tv.system_info.get("modelName"):
        #         self._attr_device_info["model"] = model

        # self._attr_extra_state_attributes = {}
        # if self._tv.sound_output is not None or self.state != States.OFF:
        #     self._attr_extra_state_attributes = {
        #         ATTR_SOUND_OUTPUT: self._client.sound_output
        #     }

    async def _connect_loop(self) -> None:
        """After sending magic packet we need to wait for the device to be accessible from network
        or maybe the device has shutdown by itself"""
        while True:
            await asyncio.sleep(DEFAULT_TIMEOUT)
            try:
                await self.connect()
                if self._tv.is_on:
                    _LOG.debug("LG TV connection succeeded")
                    self._connect_task = None
                    break
            except WEBOSTV_EXCEPTIONS:
                pass

    async def connect(self):
        if self._connecting: #TODO : to confirm or self.state != States.OFF:
            return
        try:
            self._connecting = True
            self._tv: WebOsClient = WebOsClient(
                host=self._device_config.address,
                client_key=self._device_config.key)
            await self._tv.connect()
            await self._update_states()
            if not self._mac_address:
                await self._update_system()
            await self.async_activate_websocket()
            self._attr_available = True
        except WEBOSTV_EXCEPTIONS as ex:

            self._attr_available = False
            if not self._connect_task:
                _LOG.warning("Unable to update, LG TV probably off: %s, running connect task", ex)
                self._connect_task = asyncio.create_task(self._connect_loop())
        finally:
            # Always emit connected event even if the device is unreachable (off)
            self.events.emit(Events.CONNECTED, self.id)
            self._connecting = False

    async def reconnect(self):
        """Occurs when the TV has been turned off and on : the client has to be resetted"""
        try:
            await self.connect()
        except WEBOSTV_EXCEPTIONS:
            pass

    async def _update_system(self) -> None:
        info = await self._tv.get_system_info()
        self._model_name = info.get("modelName")
        self._serial_number = info.get("serialNumber")
        info = await self._tv.get_software_info()
        self._mac_address = info.get("device_id")

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
    def source_list(self) -> list[str]:
        """Return a list of available input sources."""
        return sorted(self._sources)

    @property
    def source(self) -> str:
        """Return the current input source."""
        return self._active_source

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

    async def power_on(self) -> ucapi.StatusCodes:
        """Send power-on command to LG TV"""
        try:
            interface = os.getenv("UC_INTEGRATION_INTERFACE")
            if interface is None:
                interface = "0.0.0.0"
            _LOG.debug("LG TV power on : sending magic packet to %s on interface %s", self._mac_address, interface)
            send_magic_packet(self._mac_address, interface=interface)
            # await asyncio.sleep(10)
            # await self._tv.power_on()
            return ucapi.StatusCodes.OK
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.error("LG TV error power_on", ex)
            return ucapi.StatusCodes.BAD_REQUEST

    async def power_off(self) -> ucapi.StatusCodes:
        """Send power-off command to LG TV"""
        try:
            await self._tv.power_off()
            return ucapi.StatusCodes.OK
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.error("LG TV error power_off", ex)
            return ucapi.StatusCodes.BAD_REQUEST

    async def set_volume_level(self, volume: float | None) -> ucapi.StatusCodes:
        """Set volume level, range 0..100."""
        if volume is None:
            return ucapi.StatusCodes.BAD_REQUEST
        _LOG.debug("LG TV setting volume to %s", volume)
        try:
            await self._tv.set_volume(int(round(volume)))
            self.events.emit(Events.UPDATE, self.id, {MediaAttr.VOLUME: volume})
            return ucapi.StatusCodes.OK
        except WebOsTvCommandError:
            await self.reconnect()
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.error("LG TV error volume_up", ex)
            return ucapi.StatusCodes.BAD_REQUEST

    async def volume_up(self) -> ucapi.StatusCodes:
        """Send volume-up command to LG TV"""
        try:
            await self._tv.volume_up()
        except WebOsTvCommandError:
            await self.reconnect()
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.error("LG TV error volume_up", ex)
            return ucapi.StatusCodes.BAD_REQUEST
        return ucapi.StatusCodes.OK

    async def volume_down(self) -> ucapi.StatusCodes:
        """Send volume-down command to LG TV"""
        try:
            await self._tv.volume_down()
        except WebOsTvCommandError:
            await self.reconnect()
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.error("LG TV error volume_down", ex)
            return ucapi.StatusCodes.BAD_REQUEST
        return ucapi.StatusCodes.OK

    async def mute(self, muted: bool) -> ucapi.StatusCodes:
        """Send mute command to LG TV"""
        _LOG.debug("Sending mute: %s", muted)
        try:
            await self._tv.set_mute(muted)
        except WebOsTvCommandError:
            await self.reconnect()
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.error("LG TV error mute", ex)
            return ucapi.StatusCodes.BAD_REQUEST
        return ucapi.StatusCodes.OK

    async def async_media_play(self) -> None:
        """Send play command."""
        self._paused = False
        await self._tv.play()

    async def async_media_pause(self) -> None:
        """Send media pause command to media player."""
        self._paused = True
        await self._tv.pause()

    async def play_pause(self) -> ucapi.StatusCodes:
        """Send toggle-play-pause command to LG TV"""
        try:
            if self._paused:
                await self.async_media_play()
            else:
                await self.async_media_pause()
        except WebOsTvCommandError:
            await self.reconnect()
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.error("LG TV error play_pause", ex)
            return ucapi.StatusCodes.BAD_REQUEST
        return ucapi.StatusCodes.OK

    async def stop(self) -> ucapi.StatusCodes:
        """Send toggle-play-pause command to LG TV"""
        try:
            await self._tv.stop()
        except WebOsTvCommandError:
            await self.reconnect()
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.error("LG TV error stop", ex)
            return ucapi.StatusCodes.BAD_REQUEST
        return ucapi.StatusCodes.OK

    async def next(self) -> ucapi.StatusCodes:
        """Send next-track command to LG TV"""
        try:
            if self._tv.current_app_id == LIVE_TV_APP_ID:
                await self._tv.channel_up()
            else:
                await self._tv.fast_forward()
        except WebOsTvCommandError:
            await self.reconnect()
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.error("LG TV error next", ex)
            return ucapi.StatusCodes.BAD_REQUEST
        return ucapi.StatusCodes.OK

    async def previous(self) -> ucapi.StatusCodes:
        """Send previous-track command to LG TV"""
        try:
            if self._tv.current_app_id == LIVE_TV_APP_ID:
                await self._tv.channel_down()
            else:
                await self._tv.rewind()
        except WebOsTvCommandError:
            await self.reconnect()
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.error("LG TV error next", ex)
            return ucapi.StatusCodes.BAD_REQUEST
        return ucapi.StatusCodes.OK

    async def select_source(self, source: str | None) -> ucapi.StatusCodes:
        """Send input_source command to LG TV"""
        if not source:
            return ucapi.StatusCodes.BAD_REQUEST
        _LOG.debug("LG TV set input: %s", source)
        # switch to work.
        try:
            await self.power_on()
            for out in self._sources.values():
                if out.title == source:
                    await out.activate()
                    return ucapi.StatusCodes.OK
            _LOG.error("LG TV unable to find output: %s", source)
            return ucapi.StatusCodes.BAD_REQUEST
        except WebOsTvCommandError:
            await self.reconnect()
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.error("LG TV error select_source", ex)
            return ucapi.StatusCodes.BAD_REQUEST

    async def button(self, button: str) -> ucapi.StatusCodes:
        try:
            await self._tv.button(button)
            return ucapi.StatusCodes.OK
        except WebOsTvCommandError:
            await self.reconnect()
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.error("LG TV error select_source", ex)
            return ucapi.StatusCodes.BAD_REQUEST
