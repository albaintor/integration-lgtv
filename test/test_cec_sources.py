"""Regression tests for HDMI-CEC child source discovery and selection."""

# pylint: disable=protected-access,wrong-import-position

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import cec  # noqa: E402
import config  # noqa: E402
import lg  # noqa: E402
from ucapi import StatusCodes  # noqa: E402
from ucapi.media_player import Attributes as MediaAttr  # noqa: E402


def make_device() -> lg.LGDevice:
    """Create a device with the minimum mocked webOS state."""
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
    device._tv.tv_state = SimpleNamespace(
        apps={},
        inputs={},
        current_app_id=None,
        is_on=True,
    )
    device._tv.request = AsyncMock()
    device._tv.launch_app = AsyncMock()
    device._tv.set_input = AsyncMock()
    return device


def external_inputs() -> list[dict]:
    return [
        {"id": "HDMI_1", "label": "HDMI 1", "appId": "com.webos.app.hdmi1"},
        {"id": "HDMI_2", "label": "HDMI 2", "appId": "com.webos.app.hdmi2"},
    ]


def eim_devices() -> list[dict]:
    return [
        {
            "id": "HDMI_1",
            "appId": "com.webos.app.hdmi1",
            "label": "HDMI 1",
            "lastUniqueId": 255,
            "subList": [{"uniqueId": 11, "osdName": "SHIELD", "depth": 2}],
        },
        {
            "id": "HDMI_2",
            "appId": "com.webos.app.hdmi2",
            "label": "HDMI 2",
            "lastUniqueId": 12,
            "subList": [{"uniqueId": 12, "osdName": "Blu-ray", "depth": 2}],
        },
    ]


class CecDiscoveryTest(unittest.TestCase):
    """Test EIM parsing, parent association, and stable source labels."""

    def test_discovers_children_under_the_correct_hdmi_parent(self) -> None:
        found = cec.discover_children(external_inputs(), eim_devices())
        by_name = dict(found)

        self.assertEqual(
            by_name["SHIELD · HDMI 1"],
            cec.CecSelection("HDMI_1", "com.webos.app.hdmi1", "11"),
        )
        self.assertEqual(
            by_name["Blu-ray · HDMI 2"],
            cec.CecSelection("HDMI_2", "com.webos.app.hdmi2", "12"),
        )

    def test_accepts_child_records_without_depth(self) -> None:
        rows = [
            {
                "id": "HDMI_1",
                "appId": "com.webos.app.hdmi1",
                "subList": [{"uniqueId": 4, "osdName": "Receiver"}],
            }
        ]
        found = cec.discover_children(external_inputs(), rows)
        self.assertEqual([name for name, _ in found], ["Receiver · HDMI 1"])

    def test_duplicate_names_get_distinct_labels_and_ids(self) -> None:
        rows = [
            {
                "id": "HDMI_1",
                "appId": "com.webos.app.hdmi1",
                "subList": [
                    {"uniqueId": 3, "osdName": "Player", "depth": 2},
                    {"uniqueId": 4, "osdName": "Player", "depth": 2},
                ],
            }
        ]
        found = cec.discover_children(external_inputs(), rows)
        self.assertEqual(len(found), 2)
        self.assertNotEqual(found[0][0], found[1][0])
        self.assertEqual(
            {selection.unique_id for _, selection in found}, {"3", "4"}
        )

    def test_duplicate_name_labels_remain_attached_when_eim_order_changes(self) -> None:
        children = [
            {"uniqueId": 3, "osdName": "Player", "depth": 2},
            {"uniqueId": 4, "osdName": "Player", "depth": 2},
        ]
        first = cec.discover_children(
            external_inputs(),
            [{"id": "HDMI_1", "appId": "com.webos.app.hdmi1", "subList": children}],
        )
        reordered = cec.discover_children(
            external_inputs(),
            [
                {
                    "id": "HDMI_1",
                    "appId": "com.webos.app.hdmi1",
                    "subList": list(reversed(children)),
                }
            ],
        )

        self.assertEqual(dict(first), dict(reordered))
        self.assertEqual(
            dict(first),
            {
                "Player · HDMI 1 [CEC 3]": cec.CecSelection(
                    "HDMI_1", "com.webos.app.hdmi1", "3"
                ),
                "Player · HDMI 1 [CEC 4]": cec.CecSelection(
                    "HDMI_1", "com.webos.app.hdmi1", "4"
                ),
            },
        )

    def test_duplicate_unique_id_records_are_exposed_only_once(self) -> None:
        rows = [
            {
                "id": "HDMI_1",
                "appId": "com.webos.app.hdmi1",
                "subList": [
                    {"uniqueId": 7, "osdName": "Player", "depth": 2},
                    {"uniqueId": 7, "osdName": "Renamed duplicate", "depth": 2},
                ],
            }
        ]
        found = cec.discover_children(external_inputs(), rows)

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][1].unique_id, "7")

    def test_same_unique_id_on_different_parents_does_not_collide(self) -> None:
        rows = [
            {
                "id": "HDMI_1",
                "appId": "com.webos.app.hdmi1",
                "subList": [{"uniqueId": 5, "osdName": "Player", "depth": 2}],
            },
            {
                "id": "HDMI_2",
                "appId": "com.webos.app.hdmi2",
                "subList": [{"uniqueId": 5, "osdName": "Player", "depth": 2}],
            },
        ]
        found = cec.discover_children(external_inputs(), rows)
        self.assertEqual(len(found), 2)
        self.assertEqual(
            {selection.parent_input_id for _, selection in found},
            {"HDMI_1", "HDMI_2"},
        )

    def test_invalid_children_and_unmatched_parents_are_ignored(self) -> None:
        rows = [
            {
                "id": "HDMI_1",
                "appId": "com.webos.app.hdmi1",
                "subList": [
                    {"osdName": "No ID"},
                    {"uniqueId": 6, "osdName": ""},
                    {"uniqueId": 7, "osdName": "Bad depth", "depth": 0},
                ],
            },
            {
                "id": "HDMI_9",
                "appId": "com.webos.app.hdmi9",
                "subList": [{"uniqueId": 8, "osdName": "Unknown parent"}],
            },
        ]
        found = cec.discover_children(external_inputs(), rows)
        # An empty OSD name falls back to the unique ID; malformed depth and
        # unmatched parents are still rejected.
        self.assertEqual([name for name, _ in found], ["6 · HDMI 1"])

    def test_depth_one_name_already_exposed_as_top_level_is_suppressed(self) -> None:
        inputs = external_inputs() + [{"id": "CEC_AUDIO", "label": "Audio System"}]
        rows = [
            {
                "id": "HDMI_1",
                "appId": "com.webos.app.hdmi1",
                "subList": [
                    {"uniqueId": 9, "osdName": "Audio System", "depth": 1},
                    {"uniqueId": 10, "osdName": "Audio System", "depth": 2},
                ],
            }
        ]
        found = cec.discover_children(inputs, rows)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][1].unique_id, "10")

    def test_top_level_identity_prevents_duplicate_device(self) -> None:
        inputs = [
            {
                "id": "HDMI_1",
                "label": "HDMI 1",
                "appId": "com.webos.app.hdmi1",
                "vendorId": 123,
                "physicalAddress": 4096,
            }
        ]
        rows = [
            {
                "id": "HDMI_1",
                "appId": "com.webos.app.hdmi1",
                "subList": [
                    {
                        "uniqueId": 11,
                        "osdName": "Duplicate",
                        "vendorId": 123,
                        "physicalAddress": 4096,
                    }
                ],
            }
        ]
        self.assertEqual(cec.discover_children(inputs, rows), [])

    def test_parent_validation_and_last_unique_id_are_scoped(self) -> None:
        selection = cec.CecSelection("HDMI_2", "com.webos.app.hdmi2", "12")
        response = {
            "devices": [
                {
                    "id": "HDMI_1",
                    "appId": "com.webos.app.hdmi1",
                    "lastUniqueId": 12,
                    "subList": [{"uniqueId": 12}],
                },
                {
                    "id": "HDMI_2",
                    "appId": "com.webos.app.hdmi2",
                    "lastUniqueId": 12,
                    "subList": [{"uniqueId": 12}],
                },
            ]
        }
        self.assertTrue(cec.contains_unique_id(response, selection))
        self.assertEqual(cec.last_unique_id(response, selection), "12")

        wrong_parent_app = {
            "devices": [
                {
                    "id": "HDMI_2",
                    "appId": "com.webos.app.hdmi1",
                    "subList": [{"uniqueId": 12}],
                }
            ]
        }
        self.assertFalse(cec.contains_unique_id(wrong_parent_app, selection))

    def test_source_names_do_not_overwrite_existing_sources(self) -> None:
        rows = [
            {
                "id": "HDMI_1",
                "appId": "com.webos.app.hdmi1",
                "subList": [{"uniqueId": 4, "osdName": "Netflix"}],
            }
        ]
        found = cec.discover_children(
            external_inputs(), rows, existing_names={"Netflix · HDMI 1"}
        )
        self.assertEqual(found[0][0], "Netflix · HDMI 1 [CEC 4]")


class CecDeviceIntegrationTest(unittest.IsolatedAsyncioTestCase):
    """Test source-list integration and the guarded launch transaction."""

    async def asyncSetUp(self) -> None:
        self.device = make_device()
        self.inputs = external_inputs()
        self.device._tv.tv_state.inputs = {
            source["appId"]: source.copy() for source in self.inputs
        }
        self.device._cec_devices = eim_devices()
        self.device._tv.tv_state.current_app_id = "com.webos.app.hdmi2"
        self.device._update_sources({})

    async def test_cec_children_are_exposed_and_active_child_is_selected(self) -> None:
        self.assertIn("SHIELD · HDMI 1", self.device.source_list)
        self.assertIn("Blu-ray · HDMI 2", self.device.source_list)
        self.assertEqual(self.device.source, "Blu-ray · HDMI 2")

    async def test_source_list_updates_when_names_change_without_count_change(self) -> None:
        old_count = len(self.device.source_list)
        self.device._cec_devices[0]["subList"][0]["osdName"] = "New Player"
        updated = {}

        self.device._update_sources(updated)

        self.assertEqual(len(self.device.source_list), old_count)
        self.assertIn(MediaAttr.SOURCE_LIST, updated)
        self.assertIn("New Player · HDMI 1", updated[MediaAttr.SOURCE_LIST])

    async def test_cec_launch_uses_parent_app_and_unique_id_then_verifies(self) -> None:
        before = {"devices": eim_devices()}
        after = {"devices": eim_devices()}
        self.device._tv.request.side_effect = [before, {"returnValue": True}, after]

        with patch("lg.asyncio.sleep", new_callable=AsyncMock) as sleep:
            result = await self.device.select_source("Blu-ray · HDMI 2")

        self.assertEqual(result, StatusCodes.OK)
        self.device._tv.request.assert_has_awaits(
            [
                call(cec.CEC_EIM_STATUS, payload={}),
                call(
                    cec.CEC_LAUNCH_ENDPOINT,
                    payload={
                        "id": "com.webos.app.hdmi2",
                        "params": {"id": "uniqueId", "value": "12"},
                    },
                ),
                call(cec.CEC_EIM_STATUS, payload={}),
            ]
        )
        sleep.assert_awaited_once_with(cec.CEC_LAUNCH_SETTLE)

    async def test_stale_child_is_rejected_before_launch(self) -> None:
        self.device._tv.request.return_value = {
            "devices": [
                {
                    "id": "HDMI_2",
                    "appId": "com.webos.app.hdmi2",
                    "subList": [],
                }
            ]
        }

        result = await self.device.select_source("Blu-ray · HDMI 2")

        self.assertEqual(result, StatusCodes.BAD_REQUEST)
        self.device._tv.request.assert_awaited_once_with(
            cec.CEC_EIM_STATUS, payload={}
        )

    async def test_failed_post_launch_verification_does_not_retry_launch(self) -> None:
        before = {"devices": eim_devices()}
        after = {
            "devices": [
                {
                    "id": "HDMI_2",
                    "appId": "com.webos.app.hdmi2",
                    "lastUniqueId": 255,
                    "subList": [{"uniqueId": 12}],
                }
            ]
        }
        self.device._tv.request.side_effect = [before, {"returnValue": True}, after]

        with patch("lg.asyncio.sleep", new_callable=AsyncMock):
            result = await self.device.select_source("Blu-ray · HDMI 2")

        self.assertEqual(result, StatusCodes.BAD_REQUEST)
        launch_calls = [
            item
            for item in self.device._tv.request.await_args_list
            if item.args and item.args[0] == cec.CEC_LAUNCH_ENDPOINT
        ]
        self.assertEqual(len(launch_calls), 1)

    async def test_eim_failure_keeps_normal_sources_available(self) -> None:
        self.device._cec_devices = []
        self.device._tv.request.side_effect = RuntimeError("EIM unavailable")

        await self.device._refresh_cec_devices(force=True)
        self.device._update_sources({})

        self.assertIn("HDMI_1", self.device.source_list)
        self.assertIn("HDMI_2", self.device.source_list)
        self.assertFalse(any("· HDMI" in name for name in self.device.source_list))

    async def test_normal_app_and_input_selection_are_unchanged(self) -> None:
        self.device._tv.tv_state.apps = {
            "netflix": {"id": "netflix", "title": "Netflix"}
        }
        self.device._update_sources({})

        self.assertEqual(
            await self.device.select_source("HDMI_1"), StatusCodes.OK
        )
        self.device._tv.set_input.assert_awaited_once_with("HDMI_1")

        self.assertEqual(
            await self.device.select_source("Netflix"), StatusCodes.OK
        )
        self.device._tv.launch_app.assert_awaited_once_with("netflix")


if __name__ == "__main__":
    unittest.main()
