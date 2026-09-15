"""Regression tests for absolute volume command coalescing."""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, call, patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import config  # noqa: E402
import lg  # noqa: E402


def create_device() -> lg.LGDevice:
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
    device._tv.set_volume = AsyncMock()
    return device


async def wait_for_calls(mock: AsyncMock, count: int) -> None:
    """Wait until an async mock has received the requested number of calls."""
    async with asyncio.timeout(1):
        while mock.await_count < count:
            await asyncio.sleep(0.001)


class VolumeCoalescingTest(unittest.IsolatedAsyncioTestCase):
    """Test rate-limited absolute volume commands."""

    async def asyncSetUp(self) -> None:
        """Create a fresh device for every test."""
        self.device = create_device()

    async def asyncTearDown(self) -> None:
        """Cancel workers that may still be waiting."""
        tasks = list(self.device._background_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def test_short_burst_sends_only_latest_target(self) -> None:
        """A burst within one interval must result in one WebOS command."""
        with patch("lg.VOLUME_SET_INTERVAL", 0.05):
            await self.device.set_volume_level(10)
            await asyncio.sleep(0.01)
            await self.device.set_volume_level(20)
            await asyncio.sleep(0.01)
            await self.device.set_volume_level(30)

            await wait_for_calls(self.device._tv.set_volume, 1)
            await asyncio.sleep(0.06)

        self.device._tv.set_volume.assert_awaited_once_with(30)

    async def test_updates_during_send_are_coalesced_into_next_target(self) -> None:
        """A busy WebOS call must be followed by the latest queued target."""
        first_send_started = asyncio.Event()
        release_first_send = asyncio.Event()

        async def set_volume(target: int) -> None:
            if not first_send_started.is_set():
                first_send_started.set()
                await release_first_send.wait()

        self.device._tv.set_volume = AsyncMock(side_effect=set_volume)

        with patch("lg.VOLUME_SET_INTERVAL", 0.05):
            await self.device.set_volume_level(10)
            await asyncio.wait_for(first_send_started.wait(), timeout=1)
            await self.device.set_volume_level(20)
            await self.device.set_volume_level(30)
            release_first_send.set()

            await wait_for_calls(self.device._tv.set_volume, 2)

        self.assertEqual(
            self.device._tv.set_volume.await_args_list,
            [call(10), call(30)],
        )


if __name__ == "__main__":
    unittest.main()
