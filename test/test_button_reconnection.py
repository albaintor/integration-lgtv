"""Regression tests for button commands issued while reconnecting."""

# pylint: disable=protected-access,wrong-import-position

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from ucapi import StatusCodes  # noqa: E402
from ucapi.media_player import States  # noqa: E402

from config import LGConfigDevice  # noqa: E402
from lg import LGDevice  # noqa: E402


class ButtonReconnectionTest(unittest.IsolatedAsyncioTestCase):
    """Limit button retries while keeping the reconnection task alive."""

    async def test_unavailable_button_is_retried_only_once(self) -> None:
        """A failed retry must not start a second command-retry sequence."""
        device = object.__new__(LGDevice)
        device._available = False
        device._device_config = LGConfigDevice(
            id="test-tv",
            name="Test TV",
            address="test-tv",
            key="client-key",
            mac_address=None,
            mac_address2=None,
        )
        device._name = "Test TV"
        device._attr_state = States.ON
        device._reconnect_retry = 1
        button = AsyncMock(side_effect=RuntimeError("not connected"))
        device._tv = cast(Any, SimpleNamespace(button=button))
        connect_task = asyncio.create_task(asyncio.sleep(0))
        device._connect_task = connect_task

        result = await device.button("MENU")
        await connect_task

        self.assertEqual(result, StatusCodes.BAD_REQUEST)
        button.assert_awaited_once_with("MENU")


if __name__ == "__main__":
    unittest.main()
