"""Regression tests for Remote standby/resume behavior."""

# pylint: disable=wrong-import-position

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import driver  # noqa: E402


class StandbyReconnectTest(unittest.IsolatedAsyncioTestCase):
    """Remote wake must reconnect passively without sending Wake-on-LAN."""

    async def test_exit_standby_reconnects_without_wake_on_lan(self) -> None:
        device = SimpleNamespace(id="test-tv", host="test-tv")
        original_loop = driver._LOOP

        with (
            patch.dict(driver._configured_devices, {"test-tv": device}, clear=True),
            patch.object(driver, "connect_device", new_callable=AsyncMock) as connect,
        ):
            driver._LOOP = asyncio.get_running_loop()
            try:
                await driver.on_exit_standby()
            finally:
                driver._LOOP = original_loop

        connect.assert_awaited_once_with(device)


if __name__ == "__main__":
    unittest.main()
