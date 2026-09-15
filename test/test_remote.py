"""Regression tests for the LG remote entity."""

# pylint: disable=wrong-import-position

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from ucapi import StatusCodes  # noqa: E402
from ucapi.remote import Commands  # noqa: E402
from ucapi.ui import Buttons  # noqa: E402

import config  # noqa: E402
import remote  # noqa: E402
from const import LG_REMOTE_BUTTONS_MAPPING, LG_REMOTE_UI_PAGES  # noqa: E402


class RemotePowerTest(unittest.IsolatedAsyncioTestCase):
    """Test the remote power-toggle wiring and dispatch."""

    async def test_power_button_and_ui_use_remote_toggle(self) -> None:
        """Both default controls must target the remote toggle command."""
        power_mapping = next(
            mapping
            for mapping in LG_REMOTE_BUTTONS_MAPPING
            if mapping.button == Buttons.POWER
        )
        power_item = LG_REMOTE_UI_PAGES[0].items[0]

        self.assertEqual(power_mapping.short_press["cmd_id"], "remote.toggle")
        self.assertEqual(power_item["command"]["cmd_id"], "remote.toggle")

    async def test_toggle_command_calls_device_power_toggle(self) -> None:
        """The Integration API toggle command must reach the LG device."""
        device = Mock()
        device.state = "ON"
        device.app_buttons = []
        device.generate_apps_ui_page.return_value = None
        device.power_toggle = AsyncMock(return_value=StatusCodes.OK)
        config_device = config.LGConfigDevice(
            id="tv-id",
            name="Living room",
            address="192.0.2.10",
            key="client-key",
            mac_address=None,
            mac_address2=None,
        )
        entity = remote.LGRemote(config_device, device)

        result = await entity.command(Commands.TOGGLE, websocket=None)

        self.assertEqual(result, StatusCodes.OK)
        device.power_toggle.assert_awaited_once_with()


if __name__ == "__main__":
    unittest.main()
