"""Regression tests for the LG connection/recovery profile."""

# pylint: disable=protected-access,wrong-import-position

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import aiohttp

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from aiowebostv.webos_client import MAIN_WS_MAX_MSG_SIZE  # noqa: E402
from connection_recovery import (  # noqa: E402
    LG_HEARTBEAT,
    GracefulWebOsClient,
    LGDevice,
)


class ConnectionProfileTest(unittest.IsolatedAsyncioTestCase):
    """Keep the integration aligned with the intended LG connection profile."""

    async def test_default_heartbeat_is_30_seconds(self) -> None:
        client = GracefulWebOsClient("test-tv")
        self.assertEqual(client.heartbeat, LG_HEARTBEAT)
        self.assertEqual(client.heartbeat, 30.0)

    async def test_secure_port_is_tried_first(self) -> None:
        client = GracefulWebOsClient("test-tv")
        expected_ws = object()
        client._ws_connect = AsyncMock(return_value=expected_ws)

        result = await client._create_main_ws()

        self.assertIs(result, expected_ws)
        client._ws_connect.assert_awaited_once_with(
            "wss://test-tv:3001", MAIN_WS_MAX_MSG_SIZE
        )

    async def test_connection_rejection_falls_back_to_legacy_port(self) -> None:
        client = GracefulWebOsClient("test-tv")
        expected_ws = object()
        client._ws_connect = AsyncMock(
            side_effect=[aiohttp.ClientConnectionError("rejected"), expected_ws]
        )

        result = await client._create_main_ws()

        self.assertIs(result, expected_ws)
        self.assertEqual(
            client._ws_connect.await_args_list,
            [
                call("wss://test-tv:3001", MAIN_WS_MAX_MSG_SIZE),
                call("ws://test-tv:3000", MAIN_WS_MAX_MSG_SIZE),
            ],
        )

    async def test_secure_timeout_also_falls_back_for_legacy_tvs(self) -> None:
        client = GracefulWebOsClient("test-tv")
        expected_ws = object()
        client._ws_connect = AsyncMock(
            side_effect=[asyncio.TimeoutError(), expected_ws]
        )

        result = await client._create_main_ws()

        self.assertIs(result, expected_ws)
        self.assertEqual(
            client._ws_connect.await_args_list,
            [
                call("wss://test-tv:3001", MAIN_WS_MAX_MSG_SIZE),
                call("ws://test-tv:3000", MAIN_WS_MAX_MSG_SIZE),
            ],
        )

    async def test_duplicate_reconnect_trigger_reuses_active_task(self) -> None:
        device = object.__new__(LGDevice)
        device._device_config = SimpleNamespace(address="test-tv")
        active_task = asyncio.create_task(asyncio.sleep(0.05))
        device._connect_task = active_task
        device._reconnect_retry = 7

        returned = device.request_reconnect("button command")

        self.assertIs(returned, active_task)
        self.assertEqual(device._reconnect_retry, 7)
        await active_task


if __name__ == "__main__":
    unittest.main()
