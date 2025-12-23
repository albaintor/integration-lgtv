"""
Media-player entity functions.

:copyright: (c) 2025 by Albaintor.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import asyncio
import logging
from asyncio import shield
from typing import Any

from ucapi import EntityTypes, Remote, StatusCodes
from ucapi.media_player import States
from ucapi.remote import Attributes, Commands, Features, Options
from ucapi.remote import States as RemoteStates

from buttons import BUTTONS
from config import LGConfigDevice, create_entity_id
from const import (
    LG_REMOTE_BUTTONS_MAPPING,
    LG_REMOTE_UI_PAGES,
    LG_SIMPLE_COMMANDS_CUSTOM,
)
from lg import LGDevice

_LOG = logging.getLogger(__name__)

LG_REMOTE_STATE_MAPPING = {
    States.UNKNOWN: RemoteStates.UNKNOWN,
    States.UNAVAILABLE: RemoteStates.UNAVAILABLE,
    States.OFF: RemoteStates.OFF,
    States.ON: RemoteStates.ON,
    States.PLAYING: RemoteStates.ON,
    States.PAUSED: RemoteStates.ON,
}

COMMAND_TIMEOUT = 4.5


def get_int_param(param: str, params: dict[str, Any], default: int):
    """Get parameter in integer format."""
    # TODO bug to be fixed on UC Core : some params are sent as (empty) strings by remote (hold == "")
    value = params.get(param, default)
    if isinstance(value, str) and len(value) > 0:
        return int(float(value))
    return value


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
        # Merge static commands with dynamic app commands and custom commands
        app_commands = device.app_buttons
        simple_commands = list(BUTTONS) + list(LG_SIMPLE_COMMANDS_CUSTOM) + app_commands
        if app_commands:
            _LOG.info(
                "LGRemote: Added %d dynamic app commands: %s",
                len(app_commands),
                app_commands[:5] if len(app_commands) > 5 else app_commands,
            )

        # Merge static UI pages with dynamic apps page
        ui_pages = list(LG_REMOTE_UI_PAGES)
        try:
            apps_page = device.generate_apps_ui_page()
            if apps_page:
                _LOG.info("LGRemote: Added dynamic 'Apps' UI page with %d apps", len(apps_page.items))
                _LOG.debug(
                    "Apps page structure: page_id=%s, grid=%s, sample_items=%s",
                    apps_page.page_id,
                    apps_page.grid,
                    apps_page.items[:2] if len(apps_page.items) > 0 else [],
                )
                ui_pages.append(apps_page)
        except Exception as ex:  # pylint: disable = W0718
            _LOG.error("Failed to generate apps UI page: %s", ex, exc_info=True)

        super().__init__(
            entity_id,
            config_device.name,
            features,
            attributes,
            simple_commands=simple_commands,
            button_mapping=LG_REMOTE_BUTTONS_MAPPING,
            ui_pages=ui_pages,
        )

    async def command(self, cmd_id: str, params: dict[str, Any] | None = None) -> StatusCodes:
        """
        Media-player entity command handler.

        Called by the integration-API if a command is sent to a configured media-player entity.

        :param cmd_id: command
        :param params: optional command parameters
        :return: status code of the command request
        """
        _LOG.info("[%s] Got command request: %s %s", self.id, cmd_id, params)
        if self._device is None:
            _LOG.warning("[%s] No AndroidTV instance for this remote entity", self.id)
            return StatusCodes.NOT_FOUND
        res = StatusCodes.OK

        if cmd_id == Commands.ON:
            return await self._device.power_on()
        if cmd_id == Commands.OFF:
            return await self._device.power_off()
        if cmd_id == Commands.TOGGLE:
            return await self._device.power_toggle()
        if cmd_id in [Commands.SEND_CMD, Commands.SEND_CMD_SEQUENCE]:
            # If the duration exceeds the remote timeout, keep it running and return immediately
            try:
                async with asyncio.timeout(COMMAND_TIMEOUT):
                    res = await shield(self.send_commands(cmd_id, params))
            except asyncio.TimeoutError:
                _LOG.info("[%s] Command request timeout, keep running: %s %s", self.id, cmd_id, params)
        else:
            return StatusCodes.NOT_IMPLEMENTED
        return res

    async def send_commands(self, cmd_id: str, params: dict[str, Any] | None = None) -> StatusCodes:
        """Handle custom command or commands sequence."""
        # hold = self.get_int_param("hold", params, 0)
        delay = get_int_param("delay", params, 0)
        repeat = get_int_param("repeat", params, 1)
        command = params.get("command", "")
        res = StatusCodes.OK

        for _i in range(0, repeat):
            if cmd_id == Commands.SEND_CMD:
                result = await self.call_command(command)
                if result != StatusCodes.OK:
                    res = result
                if delay > 0:
                    await asyncio.sleep(delay / 1000)
            else:
                commands = params.get("sequence", [])
                for command in commands:
                    result = await self.call_command(command)
                    if result != StatusCodes.OK:
                        res = result
                    if delay > 0:
                        await asyncio.sleep(delay / 1000)
        return res

    async def call_command(self, command: str) -> StatusCodes:
        """Call a single command."""
        # pylint: disable=R0911
        if command == Commands.ON:
            return await self._device.power_on()
        if command == Commands.OFF:
            return await self._device.power_off()
        if command == Commands.TOGGLE:
            return await self._device.power_toggle()
        if command == "INPUT_SOURCE":
            return await self._device.select_source_next()
        if command == "TURN_SCREEN_ON":
            return await self._device.turn_screen_on()
        if command == "TURN_SCREEN_OFF":
            return await self._device.turn_screen_off()
        if command == "TURN_SCREEN_ON4":
            return await self._device.turn_screen_on(webos_ver="4")
        if command == "TURN_SCREEN_OFF4":
            return await self._device.turn_screen_off(webos_ver="4")
        if command.startswith("LAUNCH_"):
            # Handle dynamic app launch commands
            app_name = command[7:]  # Remove "LAUNCH_" prefix
            return await self._device.launch_app_by_name(app_name)
        if command in self.options[Options.SIMPLE_COMMANDS]:
            return await self._device.button(command)
        return await self._device.custom_command(command)

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
