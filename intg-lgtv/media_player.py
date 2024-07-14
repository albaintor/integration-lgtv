"""
Media-player entity functions.

:copyright: (c) 2023 by Unfolded Circle ApS.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import logging
from typing import Any

import lg
from config import LGConfigDevice, create_entity_id
from ucapi import EntityTypes, MediaPlayer, StatusCodes
from ucapi.media_player import (
    Attributes,
    Commands,
    DeviceClasses,
    MediaType,
    Options,
    States,
)

_LOG = logging.getLogger(__name__)


class LGTVMediaPlayer(MediaPlayer):
    """Representation of a Sony Media Player entity."""

    def __init__(self, config_device: LGConfigDevice, device: lg.LGDevice):
        """Initialize the class."""
        self._device: lg.LGDevice = device
        _LOG.debug("LGTVMediaPlayer init")
        entity_id = create_entity_id(config_device.id, EntityTypes.MEDIA_PLAYER)
        features = device.supported_features
        attributes = {
            Attributes.STATE: lg.LG_STATE_MAPPING.get(device.state),
            Attributes.VOLUME: device.volume_level,
            Attributes.MUTED: device.is_volume_muted,
            Attributes.SOURCE: device.source if device.source else "",
            Attributes.SOURCE_LIST: device.source_list,
            Attributes.MEDIA_IMAGE_URL: device.media_image_url if device.media_image_url else "",
            Attributes.MEDIA_TITLE: device.media_title if device.media_title else "",
            Attributes.MEDIA_TYPE: device.media_type,
        }

        # # use sound mode support & name from configuration: receiver might not yet be connected
        # if device.support_sound_mode:
        #     features.append(Features.SELECT_SOUND_MODE)
        #     attributes[Attributes.SOUND_MODE] = ""
        #     attributes[Attributes.SOUND_MODE_LIST] = []
        options = {
            Options.SIMPLE_COMMANDS: [
                "ASTERISK",
                "3D_MODE",
                "AD",  # Audio Description toggle
                "AMAZON",
                "ASPECT_RATIO",  # Quick Settings Menu - Aspect Ratio
                "CC",  # Closed Captions
                "DASH",  # Live TV
                "EXIT",
                "GUIDE",
                "INPUT_HUB",  # Home Dashboard
                "LIST",  # Live TV
                "LIVE_ZOOM",  # Live Zoom
                "MAGNIFIER_ZOOM",  # Focus Zoom
                "MYAPPS",  # Home Dashboard
                "NETFLIX",
                "PAUSE",
                "PLAY",
                "POWER",  # Power button
                "PROGRAM",  # TV Guide
                "RECENT",  # Home Dashboard - Recent Apps
                "SAP",  # Multi Audio Setting
                "SCREEN_REMOTE",  # Screen Remote
                "TELETEXT",
                "TEXTOPTION",
            ]
        }
        super().__init__(
            entity_id,
            config_device.name,
            features,
            attributes,
            device_class=DeviceClasses.RECEIVER,
            options=options,
        )

    async def command(self, cmd_id: str, params: dict[str, Any] | None = None) -> StatusCodes:
        """
        Media-player entity command handler.

        Called by the integration-API if a command is sent to a configured media-player entity.

        :param cmd_id: command
        :param params: optional command parameters
        :return: status code of the command request
        """
        # pylint: disable = R0915
        _LOG.info("Got %s command request: %s %s", self.id, cmd_id, params)

        if self._device is None:
            _LOG.warning("No LG TV instance for entity: %s", self.id)
            return StatusCodes.SERVICE_UNAVAILABLE

        if cmd_id == Commands.VOLUME:
            res = await self._device.set_volume_level(params.get("volume"))
        elif cmd_id == Commands.VOLUME_UP:
            res = await self._device.volume_up()
        elif cmd_id == Commands.VOLUME_DOWN:
            res = await self._device.volume_down()
        elif cmd_id == Commands.MUTE_TOGGLE:
            res = await self._device.mute(not self.attributes[Attributes.MUTED])
        elif cmd_id == Commands.MUTE:
            res = await self._device.mute(True)
        elif cmd_id == Commands.UNMUTE:
            res = await self._device.mute(False)
        elif cmd_id == Commands.ON:
            res = await self._device.power_on()
        elif cmd_id == Commands.OFF:
            res = await self._device.power_off()
        elif cmd_id == Commands.SELECT_SOURCE:
            res = await self._device.select_source(params.get("source"))
        elif cmd_id == Commands.NEXT:
            res = await self._device.next()
        elif cmd_id == Commands.PREVIOUS:
            res = await self._device.previous()
        elif cmd_id == Commands.CHANNEL_UP:
            res = await self._device.button("CHANNELUP")
        elif cmd_id == Commands.CHANNEL_DOWN:
            res = await self._device.button("CHANNELDOWN")
        elif cmd_id == Commands.PREVIOUS:
            res = await self._device.previous()
        elif cmd_id == Commands.PLAY_PAUSE:
            res = await self._device.play_pause()
        elif cmd_id == Commands.CURSOR_UP:
            res = await self._device.button("UP")
        elif cmd_id == Commands.CURSOR_DOWN:
            res = await self._device.button("DOWN")
        elif cmd_id == Commands.CURSOR_LEFT:
            res = await self._device.button("LEFT")
        elif cmd_id == Commands.CURSOR_RIGHT:
            res = await self._device.button("RIGHT")
        elif cmd_id == Commands.CURSOR_ENTER:
            res = await self._device.button("ENTER")
        elif cmd_id == Commands.BACK:
            res = await self._device.button("BACK")
        elif cmd_id == Commands.HOME:
            res = await self._device.button("HOME")
        elif cmd_id == Commands.SETTINGS:
            res = await self._device.button("QMENU")
        elif cmd_id == Commands.MENU:
            res = await self._device.button("INPUT_HUB")
        elif cmd_id == Commands.CONTEXT_MENU:
            res = await self._device.button("MENU")
        elif cmd_id == Commands.INFO:
            res = await self._device.button("INFO")
        elif cmd_id == Commands.DIGIT_0:
            res = await self._device.button("0")
        elif cmd_id == Commands.DIGIT_1:
            res = await self._device.button("1")
        elif cmd_id == Commands.DIGIT_2:
            res = await self._device.button("2")
        elif cmd_id == Commands.DIGIT_3:
            res = await self._device.button("3")
        elif cmd_id == Commands.DIGIT_4:
            res = await self._device.button("4")
        elif cmd_id == Commands.DIGIT_5:
            res = await self._device.button("5")
        elif cmd_id == Commands.DIGIT_6:
            res = await self._device.button("6")
        elif cmd_id == Commands.DIGIT_7:
            res = await self._device.button("7")
        elif cmd_id == Commands.DIGIT_8:
            res = await self._device.button("8")
        elif cmd_id == Commands.DIGIT_9:
            res = await self._device.button("9")
        elif cmd_id == Commands.RECORD:
            res = await self._device.button("RECORD")
        elif cmd_id == Commands.SUBTITLE:
            res = await self._device.button("CC")
        elif cmd_id == Commands.AUDIO_TRACK:
            res = await self._device.button("AD")
        elif cmd_id == Commands.FUNCTION_GREEN:
            res = await self._device.button("GREEN")
        elif cmd_id == Commands.FUNCTION_YELLOW:
            res = await self._device.button("YELLOW")
        elif cmd_id == Commands.FUNCTION_RED:
            res = await self._device.button("RED")
        elif cmd_id == Commands.FUNCTION_BLUE:
            res = await self._device.button("BLUE")
        elif cmd_id == Commands.GUIDE:
            res = await self._device.button("GUIDE")
        elif cmd_id == Commands.LIVE:
            res = await self._device.button("DASH")
        elif cmd_id == Commands.MY_RECORDINGS:
            res = await self._device.button("LIST")
        elif cmd_id == Commands.FAST_FORWARD:
            res = await self._device.button("FASTFORWARD")
        elif cmd_id == Commands.REWIND:
            res = await self._device.button("REWIND")
        elif cmd_id in self.options[Options.SIMPLE_COMMANDS]:
            res = await self._device.button(cmd_id)
        else:
            return StatusCodes.NOT_IMPLEMENTED
        return res

    def filter_changed_attributes(self, update: dict[str, Any]) -> dict[str, Any]:
        """
        Filter the given attributes and return only the changed values.

        :param update: dictionary with attributes.
        :return: filtered entity attributes containing changed attributes only.
        """
        attributes = {}

        if Attributes.STATE in update:
            state = update[Attributes.STATE]
            attributes = self._key_update_helper(Attributes.STATE, state, attributes)

        for attr in [
            Attributes.MEDIA_ARTIST,
            Attributes.MEDIA_IMAGE_URL,
            Attributes.MEDIA_TITLE,
            Attributes.MUTED,
            Attributes.SOURCE,
            Attributes.VOLUME,
        ]:
            if attr in update:
                attributes = self._key_update_helper(attr, update[attr], attributes)

        if Attributes.SOURCE_LIST in update:
            if Attributes.SOURCE_LIST in self.attributes:
                if update[Attributes.SOURCE_LIST] != self.attributes[Attributes.SOURCE_LIST]:
                    attributes[Attributes.SOURCE_LIST] = update[Attributes.SOURCE_LIST]

        if Attributes.STATE in attributes:
            if attributes[Attributes.STATE] == States.OFF:
                attributes[Attributes.MEDIA_IMAGE_URL] = ""
                attributes[Attributes.MEDIA_TITLE] = ""
                attributes[Attributes.MEDIA_TYPE] = MediaType.VIDEO
                attributes[Attributes.SOURCE] = ""
        _LOG.debug("LGTVMediaPlayer update attributes %s -> %s", update, attributes)
        return attributes

    def _key_update_helper(self, key: str, value: str | None, attributes):
        if value is None:
            return attributes

        if key in self.attributes:
            if self.attributes[key] != value:
                attributes[key] = value
        else:
            attributes[key] = value

        return attributes
