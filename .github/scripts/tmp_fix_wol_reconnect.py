from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    if old not in text:
        raise SystemExit(f"Expected block not found in {path}")
    file.write_text(text.replace(old, new, 1))


replace_once(
    "src/connection_recovery.py",
    '''    def request_reconnect(self, reason: str = "external request") -> Task[None]:
        """Start one reconnect loop, or reuse the one already running."""
        task = self._connect_task
        if task is not None and not task.done():
            _LOG.debug(
                "[%s] Reconnect already active, ignore duplicate trigger: %s",
                self._device_config.address,
                reason,
            )
            return task

        self._reconnect_retry = 0
        _LOG.debug(
            "[%s] Start reconnect loop: %s",
            self._device_config.address,
            reason,
        )
        return self._ensure_connect_task()
''',
    '''    def _try_wakeonlan(self, reason: str) -> bool:
        """Send WOL without letting a transient Remote network outage stop recovery."""
        try:
            self.wakeonlan()
        except OSError as ex:
            _LOG.debug(
                "[%s] LG WOL deferred, network not ready (%s): %s",
                self._device_config.address,
                reason,
                ex,
            )
            return False

        _LOG.debug(
            "[%s] LG WOL sent during reconnect: %s",
            self._device_config.address,
            reason,
        )
        return True

    def request_reconnect(
        self,
        reason: str = "external request",
        *,
        wake_on_lan: bool = False,
    ) -> Task[None]:
        """Start one reconnect loop, optionally arming repeated Wake-on-LAN."""
        if wake_on_lan:
            # EXIT_STANDBY can arrive before the Remote Wi-Fi route is ready. Keep
            # WOL armed even when this first packet cannot be sent so subsequent
            # reconnect retries will send it once networking is usable.
            self._retry_wakeonlan = True
            self._try_wakeonlan(reason)

        task = self._connect_task
        if task is not None and not task.done():
            _LOG.debug(
                "[%s] Reconnect already active, ignore duplicate trigger: %s",
                self._device_config.address,
                reason,
            )
            return task

        self._reconnect_retry = 0
        _LOG.debug(
            "[%s] Start reconnect loop: %s",
            self._device_config.address,
            reason,
        )
        return self._ensure_connect_task()
''',
)

replace_once(
    "src/connection_recovery.py",
    '''                if self._retry_wakeonlan:
                    self.wakeonlan()
''',
    '''                if self._retry_wakeonlan:
                    self._try_wakeonlan(f"retry {retry_count}")
''',
)

replace_once(
    "src/driver.py",
    '''async def connect_device(device: lg.LGDevice):
    """Connect device and send state."""
''',
    '''async def connect_device(device: lg.LGDevice, *, wake_on_lan: bool = False):
    """Connect device and send state, optionally waking the TV first."""
''',
)

replace_once(
    "src/driver.py",
    '''        if isinstance(device, connection_recovery.LGDevice):
            await device.request_reconnect("driver connect")
''',
    '''        if isinstance(device, connection_recovery.LGDevice):
            await device.request_reconnect(
                "driver connect", wake_on_lan=wake_on_lan
            )
''',
)

replace_once(
    "src/driver.py",
    '''            await _LOOP.create_task(connect_device(configured))
''',
    '''            await _LOOP.create_task(
                connect_device(configured, wake_on_lan=True)
            )
''',
)

replace_once(
    "src/lg.py",
    '''    async def _deferred_wakeonlan(self, delay: float):
        """Send WakeOnLan packets after given delay."""
        await asyncio.sleep(delay)
        self.wakeonlan()
''',
    '''    async def _deferred_wakeonlan(self, delay: float):
        """Best-effort delayed WakeOnLan while the Remote network comes back."""
        await asyncio.sleep(delay)
        try:
            self.wakeonlan()
        except OSError as ex:
            _LOG.debug(
                "[%s] Deferred WakeOnLan skipped, network not ready: %s",
                self._device_config.address,
                ex,
            )
''',
)

replace_once(
    "src/lg.py",
    '''            self.wakeonlan()
            # Send another WakeOnLan request after a delay in case the remote is waking up otherwise it won't be sent
            self._track_task(
                asyncio.create_task(self._deferred_wakeonlan(ERROR_OS_WAIT))
            )
            self._retry_wakeonlan = True
''',
    '''            # Arm retries before the first send: EXIT_STANDBY can be delivered
            # while the Remote still has no route, and a failed UDP broadcast must
            # not disable later Wake-on-LAN attempts.
            self._retry_wakeonlan = True
            try:
                self.wakeonlan()
            except OSError as ex:
                _LOG.debug(
                    "[%s] Initial WakeOnLan skipped, network not ready: %s",
                    self._device_config.address,
                    ex,
                )
            # Send another WakeOnLan request after a delay in case the Remote is waking up.
            self._track_task(
                asyncio.create_task(self._deferred_wakeonlan(ERROR_OS_WAIT))
            )
''',
)

replace_once(
    "test/test_connection_recovery_profile.py",
    '''from unittest.mock import AsyncMock, call
''',
    '''from unittest.mock import AsyncMock, MagicMock, call
''',
)

replace_once(
    "test/test_connection_recovery_profile.py",
    '''    async def test_duplicate_reconnect_trigger_reuses_active_task(self) -> None:
        device = object.__new__(LGDevice)
        device._device_config = SimpleNamespace(address="test-tv")
        active_task = asyncio.create_task(asyncio.sleep(0.05))
        device._connect_task = active_task
        device._reconnect_retry = 7

        returned = device.request_reconnect("button command")

        self.assertIs(returned, active_task)
        self.assertEqual(device._reconnect_retry, 7)
        await active_task
''',
    '''    async def test_duplicate_reconnect_trigger_reuses_active_task(self) -> None:
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

        returned = device.request_reconnect(
            "exit standby", wake_on_lan=True
        )

        self.assertIs(returned, active_task)
        self.assertTrue(device._retry_wakeonlan)
        device.wakeonlan.assert_called_once_with()
        await active_task
''',
)

replace_once(
    "CHANGELOG.md",
    '''- Keep a single reconnect loop active and ignore duplicate reconnect triggers instead of forcing immediate retries from button presses.
''',
    '''- Keep a single reconnect loop active and ignore duplicate reconnect triggers instead of forcing immediate retries from button presses.
- Make Wake-on-LAN best-effort during Remote wake: a transient `ENETUNREACH` can no longer terminate the reconnect loop, and `EXIT_STANDBY` keeps WOL armed for subsequent retries until the TV becomes reachable.
''',
)
