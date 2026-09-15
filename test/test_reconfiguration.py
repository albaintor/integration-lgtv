"""Regression tests for device reconfiguration."""

# pylint: disable=wrong-import-position,protected-access

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import config  # noqa: E402
import driver  # noqa: E402
import setup_flow  # noqa: E402


def create_device(address: str) -> config.LGConfigDevice:
    """Create a minimal device configuration."""
    return config.LGConfigDevice(
        id="tv-id",
        name="Living room",
        address=address,
        key="client-key",
        mac_address="00:11:22:33:44:55",
        mac_address2=None,
    )


class DevicesTest(unittest.TestCase):
    """Test persisted configuration callback behavior."""

    def test_existing_device_only_notifies_update_handler(self) -> None:
        """An address update must not also be reported as a device addition."""
        with tempfile.TemporaryDirectory() as data_path:
            add_handler = Mock()
            update_handler = Mock()
            devices = config.Devices(data_path, add_handler, Mock(), update_handler)
            devices.add_or_update(create_device("192.0.2.10"))
            add_handler.reset_mock()

            updated = create_device("192.0.2.20")
            devices.add_or_update(updated)

            self.assertEqual(devices.get("tv-id").address, "192.0.2.20")
            update_handler.assert_called_once_with(updated)
            add_handler.assert_not_called()

    def test_legacy_device_id_is_preserved(self) -> None:
        """Loading legacy configuration must not change existing entity IDs."""
        with tempfile.TemporaryDirectory() as data_path:
            devices = config.Devices(data_path, Mock(), Mock(), Mock())
            legacy = config.LGConfigDevice(
                id=None,
                name="Living room",
                address="192.0.2.10",
                key="client-key",
                mac_address=None,
                mac_address2=None,
            )
            devices.add_or_update(legacy)

            self.assertIsNone(devices.get(None).id)


class ReconfigureDeviceTest(unittest.IsolatedAsyncioTestCase):
    """Test the runtime device reconfiguration order."""

    async def test_disconnects_before_applying_address_and_reconnecting(self) -> None:
        """The old client must stop before a connection uses the new host."""
        calls = []
        updated = create_device("192.0.2.20")
        device = Mock()

        async def disconnect() -> None:
            calls.append("disconnect")

        def update_config(device_config: config.LGConfigDevice) -> None:
            calls.append(("update", device_config.address))

        async def connect() -> None:
            calls.append("connect")

        device.disconnect = disconnect
        device.update_config = update_config
        device.connect = connect

        await driver._reconfigure_device(device, updated, connect=True)

        self.assertEqual(calls, ["disconnect", ("update", "192.0.2.20"), "connect"])


class SetupFlowTest(unittest.IsolatedAsyncioTestCase):
    """Test identifiers created by the setup flow."""

    async def test_serial_number_is_used_when_software_device_id_is_missing(self) -> None:
        """New LG firmware may omit device_id, but configuration IDs cannot be null."""
        client = Mock(client_key="client-key")
        client.connect = AsyncMock()
        client.get_system_info = AsyncMock(return_value={"modelName": "OLED48C67LA", "serialNumber": "serial-123"})
        client.get_software_info = AsyncMock(return_value={"device_id": None})
        flow = setup_flow.SetupFlow(Mock())
        message = Mock(input_values={"choice": "192.0.2.10"})

        with patch("setup_flow.WebOsClient", return_value=client):
            await flow.handle_device_choice(message)

        self.assertEqual(flow._reconfigured_device.id, "serial-123")
        self.assertIsNone(flow._reconfigured_device.mac_address)

    async def test_legacy_null_id_uses_valid_setup_choice(self) -> None:
        """A null persisted ID must not produce a null dropdown value."""
        with tempfile.TemporaryDirectory() as data_path:
            devices = config.Devices(data_path, Mock(), Mock(), Mock())
            devices.add_or_update(
                config.LGConfigDevice(
                    id=None,
                    name="Living room",
                    address="192.0.2.10",
                    key="client-key",
                    mac_address=None,
                    mac_address2=None,
                )
            )
            previous_devices = config.devices
            config.devices = devices
            self.addCleanup(setattr, config, "devices", previous_devices)
            flow = setup_flow.SetupFlow(Mock())

            with patch("setup_flow.asyncio.sleep", new=AsyncMock()):
                setup_page = await flow.handle_driver_setup(Mock(reconfigure=True))
                dropdown = setup_page.settings[0]["field"]["dropdown"]
                choice = dropdown["value"]
                settings_page = await flow.handle_configuration_mode(
                    Mock(input_values={"action": "configure", "choice": choice})
                )

            self.assertIsInstance(choice, str)
            self.assertIsNotNone(choice)
            self.assertEqual(settings_page.settings[1]["field"]["text"]["value"], "192.0.2.10")


if __name__ == "__main__":
    unittest.main()
