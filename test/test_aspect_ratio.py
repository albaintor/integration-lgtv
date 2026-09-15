"""Tests for the aspect ratio select entity."""

# pylint: disable=protected-access,wrong-import-position

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from ucapi import StatusCodes  # noqa: E402
from ucapi.select import Attributes  # noqa: E402

import config  # noqa: E402
import lg  # noqa: E402
import selector  # noqa: E402
from const import LG_ADDITIONAL_ENDPOINTS  # noqa: E402


def create_device(model_name: str = "OLED55C16LA") -> lg.LGDevice:
    """Create an LG device with a mocked WebOS client."""
    device = lg.LGDevice(
        config.LGConfigDevice(
            id="tv-id",
            name="Living room",
            address="192.0.2.10",
            key="client-key",
            mac_address=None,
            mac_address2=None,
        )
    )
    device._tv = Mock()
    device._tv.tv_info = Mock(system={"modelName": model_name})
    device._tv.request = AsyncMock()
    return device


class AspectRatioTest(unittest.IsolatedAsyncioTestCase):
    """Test generation lookup and webOS aspect ratio commands."""

    async def test_model_generation_supports_numeric_and_cx_names(self) -> None:
        """LG numeric generations and the CX generation must be recognized."""
        self.assertEqual(create_device("OLED55C16LA").model_version, "C1")
        self.assertEqual(create_device("OLED55CX6LA").model_version, "CX")

    async def test_generation_options_are_exposed_by_the_select(self) -> None:
        """The select exposes the labels configured for the detected generation."""
        device = create_device()
        device._update_aspect_ratios()
        device._aspect_ratio_attributes("16x9")
        entity = selector.LGAspectRatioSelect(device._device_config, device)

        self.assertEqual(entity.current_option, "16:9")
        self.assertEqual(
            entity.select_options,
            ["16:9", "Original", "4:3", "Vertical zoom", "All-direction zoom"],
        )

    async def test_unknown_tv_value_is_added_to_the_options(self) -> None:
        """A source-specific value must not leave the select in an invalid state."""
        device = create_device()
        device._update_aspect_ratios()

        attributes = device._aspect_ratio_attributes("full_wide")

        self.assertEqual(device.aspect_ratio, "full_wide")
        self.assertIn("full_wide", device.aspect_ratios)
        self.assertEqual(attributes[Attributes.CURRENT_OPTION], "full_wide")
        self.assertIn("full_wide", attributes[Attributes.OPTIONS])

    async def test_set_aspect_ratio_uses_the_current_app_setting(self) -> None:
        """Selecting a label sends its raw value for the active application."""
        device = create_device()
        device._update_aspect_ratios()
        device._tv.request.return_value = {"returnValue": True}

        result = await device.set_aspect_ratio("Original")

        self.assertEqual(result, StatusCodes.OK)
        device._tv.request.assert_awaited_once_with(
            LG_ADDITIONAL_ENDPOINTS["SET_SYSTEM_SETTINGS"],
            {
                "category": "aspectRatio",
                "settings": {"arcPerApp": "original"},
                "current_app": True,
            },
        )
        self.assertEqual(device.aspect_ratio, "Original")


if __name__ == "__main__":
    unittest.main()
