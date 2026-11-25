"""Regression tests for LG power-off during Remote standby recovery."""

# pylint: disable=protected-access,wrong-import-position

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import aiowebostv.endpoints as ep  # noqa: E402
from ucapi import StatusCodes  # noqa: E402
from ucapi.media_player import States  # noqa: E402

from lg import LGDevice, POWER_OFF_DEFERRED_LIFETIME  # noqa: E402


class PowerOffReconnectTest(unittest.IsolatedAsyncioTestCase):
    """Power-off intent must survive an input WebSocket TLS timeout."""

    async def asyncSetUp(self) -> None:
        self.device = object.__new__(LGDevice)
        self.device._device_config = SimpleNamespace(address="test-tv")
        self.device._name = "Test TV"
        self.device._available = False
        self.device._attr_state = States.ON
        self.device._retry_wakeonlan = True
        self.device._connecting_tv = None
        self.device._reconnect_retry = 0
        self.device._deferred_commands = asyncio.Queue()
        self.device._power_off_generation = 0
        self.device.event_loop = asyncio.get_running_loop()
        self.device._tv = SimpleNamespace(
            connection=None,
            command=AsyncMock(),
            get_power_state=AsyncMock(),
        )

    async def _queue_power_off(self):
        reconnect = asyncio.create_task(asyncio.sleep(0))
        with patch.object(
            LGDevice, "_ensure_connect_task", return_value=reconnect
        ) as ensure_connect:
            result = await self.device.power_off()
        await reconnect

        self.assertEqual(result, StatusCodes.OK)
        self.assertEqual(self.device._deferred_commands.qsize(), 1)
        self.assertFalse(self.device._retry_wakeonlan)
        ensure_connect.assert_called_once()
        self.device._tv.command.assert_not_awaited()
        self.device._tv.get_power_state.assert_not_awaited()
        return self.device._deferred_commands._queue[0]

    async def test_unavailable_power_off_is_buffered_immediately(self) -> None:
        command = await self._queue_power_off()
        self.assertEqual(command.ttl, POWER_OFF_DEFERRED_LIFETIME)

    async def test_power_off_survives_the_old_30_second_timeout(self) -> None:
        command = await self._queue_power_off()
        command.created_at -= 35
        self.device._available = True
        self.device._tv.connection = object()

        await self.device._drain_deferred_commands()
        self.device._tv.command.assert_awaited_once_with(
            "request", ep.POWER_OFF
        )
        self.assertEqual(self.device._attr_state, States.OFF)
        self.assertTrue(command.future.done())
        self.assertEqual(command.future.result(), StatusCodes.OK)

    async def test_early_power_off_uses_registered_main_socket(self) -> None:
        """No need to wait for TLS on the pointer WebSocket."""
        provisional = SimpleNamespace(
            connection=SimpleNamespace(closed=False),
            command=AsyncMock(),
        )
        self.device._connecting_tv = provisional

        with patch.object(LGDevice, "_ensure_connect_task") as reconnect:
            result = await self.device.power_off()

        self.assertEqual(result, StatusCodes.OK)
        provisional.command.assert_awaited_once_with("request", ep.POWER_OFF)
        reconnect.assert_not_called()
        self.assertEqual(self.device._deferred_commands.qsize(), 0)
        self.device._tv.command.assert_not_awaited()
        self.assertEqual(self.device._attr_state, States.OFF)

    async def test_early_power_off_failure_falls_back_to_queue(self) -> None:
        provisional = SimpleNamespace(
            connection=SimpleNamespace(closed=False),
            command=AsyncMock(side_effect=OSError("connection lost")),
        )
        self.device._connecting_tv = provisional
        reconnect_task = asyncio.create_task(asyncio.sleep(0))

        with (
            patch.object(
                LGDevice, "_ensure_connect_task", return_value=reconnect_task
            ),
            self.assertLogs("lg", level="WARNING"),
        ):
            result = await self.device.power_off()
        await reconnect_task

        self.assertEqual(result, StatusCodes.OK)
        self.assertEqual(self.device._deferred_commands.qsize(), 1)

    async def test_power_off_expires_after_bounded_lifetime(self) -> None:
        command = await self._queue_power_off()
        command.created_at -= POWER_OFF_DEFERRED_LIFETIME + 1
        self.device._available = True
        self.device._tv.connection = object()

        with self.assertLogs("lg", level="WARNING"):
            await self.device._drain_deferred_commands()
            await asyncio.sleep(0)

        self.device._tv.command.assert_not_awaited()
        self.assertIsInstance(command.future.exception(), asyncio.TimeoutError)

    async def test_connected_power_off_does_not_query_tv_state(self) -> None:
        self.device._available = True
        self.device._tv.connection = object()
        result = await self.device.power_off()

        self.assertEqual(result, StatusCodes.OK)
        self.device._tv.command.assert_awaited_once_with(
            "request", ep.POWER_OFF
        )
        self.device._tv.get_power_state.assert_not_awaited()
        self.assertEqual(self.device._attr_state, States.OFF)

    async def test_power_on_cancels_only_older_off_commands(self) -> None:
        off = await self._queue_power_off()
        other = AsyncMock(return_value=StatusCodes.OK)
        other_future = await self.device.defer_command(other)
        with patch.object(LGDevice, "_wake_for_command", new_callable=AsyncMock):
            await self.device.power_on()
        self.assertTrue(off.future.cancelled())
        self.assertEqual(self.device._deferred_commands.qsize(), 1)
        await self.device._drain_deferred_commands()
        other.assert_awaited_once()
        self.assertEqual(other_future.result(), StatusCodes.OK)
        self.device._tv.command.assert_not_awaited()

    async def test_source_selection_cancels_off_before_reconnection(self) -> None:
        off = await self._queue_power_off()
        with patch.object(LGDevice, "_select_source", new_callable=AsyncMock) as select:
            await self.device.select_source("HDMI_1")
        select.assert_awaited_once_with("HDMI_1")
        self.assertTrue(off.future.cancelled())
        self.assertTrue(self.device._deferred_commands.empty())

    async def test_new_off_after_power_on_is_not_cancelled(self) -> None:
        old = await self._queue_power_off()
        with patch.object(LGDevice, "_wake_for_command", new_callable=AsyncMock):
            await self.device.power_on()
        new = await self._queue_power_off()
        self.assertTrue(old.future.cancelled())
        self.assertFalse(new.future.cancelled())
        await self.device._drain_deferred_commands()
        self.device._tv.command.assert_awaited_once_with("request", ep.POWER_OFF)

    async def test_off_superseded_during_early_send_failure(self) -> None:
        async def fail_after_on(*args):
            with patch.object(LGDevice, "_wake_for_command", new_callable=AsyncMock):
                await self.device.power_on()
            raise OSError("connection lost")

        self.device._connecting_tv = SimpleNamespace(
            connection=SimpleNamespace(closed=False),
            command=AsyncMock(side_effect=fail_after_on),
        )
        self.assertEqual(await self.device.power_off(), StatusCodes.OK)
        self.assertTrue(self.device._deferred_commands.empty())


if __name__ == "__main__":
    unittest.main()
