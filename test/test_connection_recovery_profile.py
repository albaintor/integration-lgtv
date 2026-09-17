"""Regression tests for the LG connection/recovery profile."""

# pylint: disable=protected-access,wrong-import-position

import asyncio
import errno
import ssl
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import aiohttp

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from aiowebostv.webos_client import MAIN_WS_MAX_MSG_SIZE  # noqa: E402
from connection_recovery import (  # noqa: E402
    LG_CONNECT_TIMEOUT,
    LG_HEARTBEAT,
    GracefulWebOsClient,
    LGDevice,
)
from lg_tcp_connector import LGDiagnosticTCPConnector  # noqa: E402


class ConnectionProfileTest(unittest.IsolatedAsyncioTestCase):
    """Keep the integration aligned with the intended LG connection profile."""

    async def test_default_connect_timeout_is_6_seconds(self) -> None:
        client = GracefulWebOsClient("test-tv")
        self.assertEqual(client.timeout_connect, LG_CONNECT_TIMEOUT)
        self.assertEqual(client.timeout_connect, 6.0)

    async def test_default_heartbeat_is_30_seconds(self) -> None:
        client = GracefulWebOsClient("test-tv")
        self.assertEqual(client.heartbeat, LG_HEARTBEAT)
        self.assertEqual(client.heartbeat, 30.0)

    async def test_default_session_uses_tcp_tls_diagnostic_connector(self) -> None:
        client = GracefulWebOsClient("test-tv")
        client._ensure_client_session()
        try:
            self.assertIsNotNone(client.client_session)
            self.assertIsInstance(
                client.client_session.connector,
                LGDiagnosticTCPConnector,
            )
        finally:
            await client.close_client_session()

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
        refused = aiohttp.ClientConnectionError("rejected")
        refused.os_error = OSError(errno.ECONNREFUSED, "Connection refused")
        client._ws_connect = AsyncMock(side_effect=[refused, expected_ws])

        result = await client._create_main_ws()

        self.assertIs(result, expected_ws)
        self.assertEqual(
            client._ws_connect.await_args_list,
            [
                call("wss://test-tv:3001", MAIN_WS_MAX_MSG_SIZE),
                call("ws://test-tv:3000", MAIN_WS_MAX_MSG_SIZE),
            ],
        )

    async def test_secure_timeout_does_not_fall_back_to_legacy_port(self) -> None:
        client = GracefulWebOsClient("test-tv")
        client._ws_connect = AsyncMock(side_effect=asyncio.TimeoutError())

        with self.assertRaises(asyncio.TimeoutError):
            await client._create_main_ws()

        client._ws_connect.assert_awaited_once_with(
            "wss://test-tv:3001", MAIN_WS_MAX_MSG_SIZE
        )

    async def test_host_unreachable_does_not_fall_back_to_legacy_port(self) -> None:
        client = GracefulWebOsClient("test-tv")
        unreachable = aiohttp.ClientConnectionError("unreachable")
        unreachable.os_error = OSError(errno.EHOSTUNREACH, "No route to host")
        client._ws_connect = AsyncMock(side_effect=unreachable)

        with self.assertRaises(aiohttp.ClientConnectionError):
            await client._create_main_ws()

        client._ws_connect.assert_awaited_once_with(
            "wss://test-tv:3001", MAIN_WS_MAX_MSG_SIZE
        )

    async def test_tls_context_is_fresh_for_each_connection(self) -> None:
        first = GracefulWebOsClient._new_ssl_context()
        second = GracefulWebOsClient._new_ssl_context()

        self.assertIsNot(first, second)
        self.assertFalse(first.check_hostname)
        self.assertEqual(first.verify_mode, ssl.CERT_NONE)
        self.assertFalse(second.check_hostname)
        self.assertEqual(second.verify_mode, ssl.CERT_NONE)

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

    async def test_wake_trigger_survives_network_unreachable(self) -> None:
        device = object.__new__(LGDevice)
        device._device_config = SimpleNamespace(address="test-tv")
        device._retry_wakeonlan = False
        device.wakeonlan = MagicMock(
            side_effect=OSError(errno.ENETUNREACH, "Network is unreachable")
        )
        active_task = asyncio.create_task(asyncio.sleep(0.05))
        device._connect_task = active_task
        device._reconnect_retry = 3

        returned = device.request_reconnect("exit standby", wake_on_lan=True)

        self.assertIs(returned, active_task)
        self.assertTrue(device._retry_wakeonlan)
        device.wakeonlan.assert_called_once_with()
        await active_task


if __name__ == "__main__":
    unittest.main()
