"""
Media-player entity functions.

:copyright: (c) 2025 by Albaintor.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import logging
from typing import Any

from ucapi import EntityTypes, MediaPlayer, StatusCodes
from ucapi.media_player import (
    Attributes,
    Commands,
    DeviceClasses,
    MediaContentType,
    Options,
    States,
)

import lg
from config import LGConfigDevice, LGEntity, create_entity_id
from const import LG_SIMPLE_COMMANDS, LG_SIMPLE_COMMANDS_CUSTOM, filter_attributes

# pylint: disable = R0801

_LOG = logging.getLogger(__name__)


class LGTVMediaPlayer(MediaPlayer, LGEntity):
    """Representation of a Sony Media Player entity."""

    def __init__(self, config_device: LGConfigDevice, device: lg.LGDevice):
        """Initialize the class."""
        self._device: lg.LGDevice = device
        self._config_device = config_device
        entity_id = create_entity_id(config_device.id, EntityTypes.MEDIA_PLAYER)
        features = device.supported_features
        # Merge static commands with dynamic app commands
        app_commands = device.app_buttons
        simple_commands = list(LG_SIMPLE_COMMANDS) + app_commands
        if app_commands:
            _LOG.info(
                "LGTVMediaPlayer: Added %d dynamic app commands: %s",
                len(app_commands),
                app_commands[:5] if len(app_commands) > 5 else app_commands,
            )
        options: dict[str, Any] = {Options.SIMPLE_COMMANDS: simple_commands}
        super().__init__(
            entity_id,
            config_device.name,
            features,
            filter_attributes(device.attributes, Attributes),
            device_class=DeviceClasses.RECEIVER,
            options=options,
        )

    @property
    def deviceid(self) -> str:
        """Return the device identifier."""
        return self._config_device.id

    async def command(
        self, cmd_id: str, params: dict[str, Any] | None = None, *, websocket: Any
    ) -> StatusCodes:
        """
        Media-player entity command handler.

        Called by the integration-API if a command is sent to a configured media-player entity.

        :param cmd_id: command
        :param params: optional command parameters
        :param websocket: optional websocket connection. Allows for directed event
                          callbacks instead of broadcasts.
        :return: status code of the command request
        """
        # pylint: disable = R0915
        _LOG.info("Got %s command request: %s %s", self.id, cmd_id, params)
        params = params or {}

        if self._device is None:
            _LOG.warning("No LG TV instance for entity: %s", self.id)
            return StatusCodes.SERVICE_UNAVAILABLE

        simple_commands = (self.options or {}).get(Options.SIMPLE_COMMANDS, [])
        match cmd_id:
            case Commands.VOLUME:
                return await self._device.set_volume_level(params.get("volume"))
            case Commands.VOLUME_UP:
                return await self._device.volume_up()
            case Commands.VOLUME_DOWN:
                return await self._device.volume_down()
            case Commands.MUTE_TOGGLE:
                return await self._device.mute(not self.attributes[Attributes.MUTED])
            case Commands.MUTE:
                return await self._device.mute(True)
            case Commands.UNMUTE:
                return await self._device.mute(False)
            case Commands.ON:
                return await self._device.power_on()
            case Commands.OFF:
                return await self._device.power_off()
            case Commands.TOGGLE:
                return await self._device.power_toggle()
            case Commands.SELECT_SOURCE:
                return await self._device.select_source(params.get("source"))
            case Commands.NEXT:
                return await self._device.next()
            case Commands.PREVIOUS:
                return await self._device.previous()
            case Commands.CHANNEL_UP:
                return await self._device.button("CHANNELUP")
            case Commands.CHANNEL_DOWN:
                return await self._device.button("CHANNELDOWN")
            case Commands.PLAY_PAUSE:
                return await self._device.play_pause()
            case Commands.CURSOR_UP:
                return await self._device.button("UP")
            case Commands.CURSOR_DOWN:
                return await self._device.button("DOWN")
            case Commands.CURSOR_LEFT:
                return await self._device.button("LEFT")
            case Commands.CURSOR_RIGHT:
                return await self._device.button("RIGHT")
            case Commands.CURSOR_ENTER:
                return await self._device.button("ENTER")
            case Commands.BACK:
                return await self._device.button("BACK")
            case Commands.HOME:
                return await self._device.button_retry("HOME")
            case Commands.SETTINGS:
                return await self._device.button("QMENU")
            case Commands.MENU:
                return await self._device.button("INPUT_HUB")
            case Commands.CONTEXT_MENU:
                return await self._device.button("MENU")
            case Commands.INFO:
                return await self._device.button("INFO")
            case Commands.DIGIT_0:
                return await self._device.button("0")
            case Commands.DIGIT_1:
                return await self._device.button("1")
            case Commands.DIGIT_2:
                return await self._device.button("2")
            case Commands.DIGIT_3:
                return await self._device.button("3")
            case Commands.DIGIT_4:
                return await self._device.button("4")
            case Commands.DIGIT_5:
                return await self._device.button("5")
            case Commands.DIGIT_6:
                return await self._device.button("6")
            case Commands.DIGIT_7:
                return await self._device.button("7")
            case Commands.DIGIT_8:
                return await self._device.button("8")
            case Commands.DIGIT_9:
                return await self._device.button("9")
            case Commands.RECORD:
                return await self._device.button("RECORD")
            case Commands.SUBTITLE:
                return await self._device.button("CC")
            case Commands.AUDIO_TRACK:
                return await self._device.button("AD")
            case Commands.FUNCTION_GREEN:
                return await self._device.button("GREEN")
            case Commands.FUNCTION_YELLOW:
                return await self._device.button("YELLOW")
            case Commands.FUNCTION_RED:
                return await self._device.button("RED")
            case Commands.FUNCTION_BLUE:
                return await self._device.button("BLUE")
            case Commands.GUIDE:
                return await self._device.button("GUIDE")
            case Commands.LIVE:
                return await self._device.button("DASH")
            case Commands.MY_RECORDINGS:
                return await self._device.button("LIST")
            case Commands.FAST_FORWARD:
                return await self._device.button("FASTFORWARD")
            case Commands.REWIND:
                return await self._device.button("REWIND")
            case Commands.SELECT_SOUND_MODE:
                return await self._device.select_sound_output(params.get("mode"))
            case command if command in simple_commands:
                match command:
                    case command if command.startswith("LAUNCH_"):
                        # Handle dynamic app launch commands
                        app_name = command[7:]  # Remove "LAUNCH_" prefix
                        return await self._device.launch_app_by_name(app_name)
                    case "INPUT_SOURCE":
                        return await self._device.select_source_next()
                    case "TURN_SCREEN_ON":
                        return await self._device.turn_screen_on()
                    case "TURN_SCREEN_OFF":
                        return await self._device.turn_screen_off()
                    case "TURN_SCREEN_ON4":
                        return await self._device.turn_screen_on(webos_ver="4")
                    case "TURN_SCREEN_OFF4":
                        return await self._device.turn_screen_off(webos_ver="4")
                    case command if command in LG_SIMPLE_COMMANDS_CUSTOM:
                        return StatusCodes.NOT_IMPLEMENTED
                    case command:
                        return await self._device.button(command)
            case _:
                return StatusCodes.NOT_IMPLEMENTED

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
            Attributes.SOUND_MODE,
            Attributes.SOUND_MODE_LIST,
        ]:
            if attr in update:
                attributes = self._key_update_helper(attr, update[attr], attributes)

        if Attributes.SOURCE_LIST in update:
            if Attributes.SOURCE_LIST in self.attributes:
                if (
                    update[Attributes.SOURCE_LIST]
                    != self.attributes[Attributes.SOURCE_LIST]
                ):
                    attributes[Attributes.SOURCE_LIST] = update[Attributes.SOURCE_LIST]

        if Attributes.STATE in attributes:
            if attributes[Attributes.STATE] == States.OFF:
                attributes[Attributes.MEDIA_IMAGE_URL] = ""
                attributes[Attributes.MEDIA_TITLE] = ""
                attributes[Attributes.MEDIA_TYPE] = MediaContentType.VIDEO
                attributes[Attributes.SOURCE] = ""
        _LOG.debug("LGTVMediaPlayer update attributes %s -> %s", update, attributes)
        return attributes

    def _key_update_helper(
        self, key: str, value: Any, attributes: dict[str, Any]
    ) -> dict[str, Any]:
        if value is None:
            return attributes

        if key in self.attributes:
            if self.attributes[key] != value:
                attributes[key] = value
        else:
            attributes[key] = value

        return attributes
