"""
Media-player entity functions.

:copyright: (c) 2023 by Unfolded Circle ApS.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""
import asyncio
import logging
from typing import Any

from aiowebostv.buttons import BUTTONS
from ucapi.media_player import States

from config import create_entity_id, LGConfigDevice
from lg import LGDevice
from ucapi import EntityTypes, Remote, StatusCodes
from ucapi.remote import Attributes, Commands, States as RemoteStates, Options, Features
from const import LG_REMOTE_BUTTONS_MAPPING, LG_REMOTE_UI_PAGES, LG_SIMPLE_COMMANDS_CUSTOM

_LOG = logging.getLogger(__name__)

LG_REMOTE_STATE_MAPPING = {
    States.UNKNOWN: RemoteStates.UNKNOWN,
    States.UNAVAILABLE: RemoteStates.UNAVAILABLE,
    States.OFF: RemoteStates.OFF,
    States.ON: RemoteStates.ON,
    States.PLAYING: RemoteStates.ON,
    States.PAUSED: RemoteStates.ON,
}


class LGRemote(Remote):
    """Representation of a LG Remote entity."""

    def __init__(self, config_device: LGConfigDevice, device: LGDevice):
        """Initialize the class."""
        self._device = device
        _LOG.debug("LgRemote init")
        entity_id = create_entity_id(config_device.id, EntityTypes.REMOTE)
        features = [Features.SEND_CMD, Features.ON_OFF, Features.TOGGLE]
        attributes = {
            Attributes.STATE: LG_REMOTE_STATE_MAPPING.get(device.state),
        }
        super().__init__(
            entity_id,
            config_device.name,
            features,
            attributes,
            simple_commands=BUTTONS,
            button_mapping=LG_REMOTE_BUTTONS_MAPPING,
            ui_pages=LG_REMOTE_UI_PAGES
        )

    @staticmethod
    def getIntParam(self, param: str, params: dict[str, Any], default: int):
        # TODO bug to be fixed on UC Core : some params are sent as (empty) strings by remote (hold == "")
        if params is None or param is None:
            return default
        value = params.get(param, default)
        if isinstance(value, str) and len(value) > 0:
            return int(float(value))
        else:
            return default

    async def command(self, cmd_id: str, params: dict[str, Any] | None = None) -> StatusCodes:
        """
        Media-player entity command handler.

        Called by the integration-API if a command is sent to a configured media-player entity.

        :param cmd_id: command
        :param params: optional command parameters
        :return: status code of the command request
        """
        _LOG.info("Got %s command request: %s %s", self.id, cmd_id, params)

        if self._device is None:
            _LOG.warning("No Kodi instance for entity: %s", self.id)
            return StatusCodes.SERVICE_UNAVAILABLE

        repeat = LGRemote.getIntParam("repeat", params, 1)
        res = StatusCodes.OK
        for i in range(0, repeat):
            res = await self.handle_command(cmd_id, params)
        return res

    async def handle_command(self, cmd_id: str, params: dict[str, Any] | None = None) -> StatusCodes:
        #hold = LGRemote.getIntParam("hold", params, 0)
        delay = LGRemote.getIntParam("delay", params, 0)
        command = params.get("command", "")
        res = None

        if command in self.options[Options.SIMPLE_COMMANDS]:
            if cmd_id in LG_SIMPLE_COMMANDS_CUSTOM:
                if cmd_id == "INPUT_SOURCE":
                    res = await self._device.select_source_next()
            else:
                res = await self._device.button(command)
        elif cmd_id == Commands.ON:
            return await self._device.power_on()
        elif cmd_id == Commands.OFF:
            return await self._device.power_off()
        elif cmd_id == Commands.TOGGLE:
            return await self._device.power_toggle()
        elif cmd_id == Commands.SEND_CMD:
            if command == Commands.ON:
                return await self._device.power_on()
            elif command == Commands.OFF:
                return await self._device.power_off()
            elif command == Commands.TOGGLE:
                return await self._device.power_toggle()
            return await self._device.button(command)
        elif cmd_id == Commands.SEND_CMD_SEQUENCE:
            commands = params.get("sequence", [])  #.split(",")
            res = StatusCodes.OK
            for command in commands:
                res = await self.handle_command(Commands.SEND_CMD, {"command": command, "params": params})
                if delay > 0:
                    await asyncio.sleep(delay)
        else:
            return StatusCodes.NOT_IMPLEMENTED
        if delay > 0 and cmd_id != Commands.SEND_CMD_SEQUENCE:
            await asyncio.sleep(delay)
        return res

    def _key_update_helper(self, key: str, value: str | None, attributes):
        if value is None:
            return attributes

        if key in self.attributes:
            if self.attributes[key] != value:
                attributes[key] = value
        else:
            attributes[key] = value

        return attributes

    def filter_changed_attributes(self, update: dict[str, Any]) -> dict[str, Any]:
        """
        Filter the given attributes and return only the changed values.

        :param update: dictionary with attributes.
        :return: filtered entity attributes containing changed attributes only.
        """
        attributes = {}

        if Attributes.STATE in update:
            state = LG_REMOTE_STATE_MAPPING.get(update[Attributes.STATE])
            attributes = self._key_update_helper(Attributes.STATE, state, attributes)

        _LOG.debug("LgRemote update attributes %s -> %s", update, attributes)
        return attributes
