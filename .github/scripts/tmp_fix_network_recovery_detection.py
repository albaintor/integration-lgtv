from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    if old not in text:
        raise SystemExit(f"Expected block not found in {path}: {old[:100]!r}")
    file.write_text(text.replace(old, new, 1))


replace_once(
    "src/connection_recovery.py",
    '''                network_path_errno: int | None = None
                try:
                    await self.connect()
                    if self._tv.tv_state.is_on:
                        _LOG.debug(
                            "[%s] LG TV connection succeeded",
                            self._device_config.address,
                        )
                        self._update_picture_modes()
                        break
                except CancelledError:
''',
    '''                network_path_failure = False
                try:
                    await self.connect()
                    if self._tv.tv_state.is_on:
                        _LOG.debug(
                            "[%s] LG TV connection succeeded",
                            self._device_config.address,
                        )
                        self._update_picture_modes()
                        break

                    # lg.LGDevice.connect() logs and absorbs WEBOSTV_EXCEPTIONS.
                    # If it returned unavailable, verify the LAN path directly
                    # instead of waiting for an exception that will never escape.
                    if not self._available and not await self._network_path_ready():
                        network_path_failure = True
                        _LOG.debug(
                            "[%s] LG connect ended unavailable and TCP endpoints "
                            "are unreachable; switch to fast TCP probes",
                            self._device_config.address,
                        )
                except CancelledError:
''',
)

replace_once(
    "src/connection_recovery.py",
    '''                    if network_path_errno is not None:
                        _LOG.debug(
                            "[%s] LG network path failure errno=%s; "
                            "switch to fast TCP probes",
                            self._device_config.address,
                            network_path_errno,
                        )
''',
    '''                    if network_path_errno is not None:
                        network_path_failure = True
                        _LOG.debug(
                            "[%s] LG network path failure errno=%s; "
                            "switch to fast TCP probes",
                            self._device_config.address,
                            network_path_errno,
                        )
''',
)

replace_once(
    "src/connection_recovery.py",
    '''                if network_path_errno is not None:
                    network_recovery = True
                    continue
''',
    '''                if network_path_failure:
                    network_recovery = True
                    continue
''',
)

replace_once(
    "src/driver.py",
    '''        else:
            await device.connect()
        _LOG.debug(
            "[%s] Device %s connected, sending attributes for subscribed entities",
            device.host,
            device.id,
        )
''',
    '''        else:
            await device.connect()
        if not device.available:
            _LOG.debug(
                "[%s] Device %s reconnect ended without an active LG connection",
                device.host,
                device.id,
            )
            return
        _LOG.debug(
            "[%s] Device %s connected, sending attributes for subscribed entities",
            device.host,
            device.id,
        )
''',
)

replace_once(
    "test/test_connection_recovery_profile.py",
    '''        device._update_picture_modes.assert_called_once_with()


if __name__ == "__main__":
''',
    '''        device._update_picture_modes.assert_called_once_with()

    async def test_swallowed_network_error_switches_to_fast_probe(self) -> None:
        device = object.__new__(LGDevice)
        device._device_config = SimpleNamespace(address="test-tv")
        device._retry_wakeonlan = False
        device._connect_task = None
        device._reconnect_retry = 0
        device._attr_state = States.OFF
        device._available = False
        device._tv = SimpleNamespace(tv_state=SimpleNamespace(is_on=False))

        connect_calls = 0

        async def connect_like_production() -> None:
            nonlocal connect_calls
            connect_calls += 1
            if connect_calls == 1:
                # Production connect() logs the connector error, marks the
                # device unavailable and returns without re-raising it.
                device._available = False
                device._tv.tv_state.is_on = False
                return
            device._available = True
            device._tv.tv_state.is_on = True

        device.connect = AsyncMock(side_effect=connect_like_production)
        device._network_path_ready = AsyncMock(return_value=False)
        device._wait_for_network_path = AsyncMock(return_value=True)
        device._update_picture_modes = MagicMock()

        await device._connect_loop()

        self.assertEqual(device.connect.await_count, 2)
        device._network_path_ready.assert_awaited_once_with()
        device._wait_for_network_path.assert_awaited_once_with()
        device._update_picture_modes.assert_called_once_with()


if __name__ == "__main__":
''',
)

replace_once(
    "CHANGELOG.md",
    "- After `ENETUNREACH`/`EHOSTUNREACH`, switch to short raw TCP probes of LG ports 3001/3000 before resuming full TLS/WebSocket negotiation, so Remote LAN recovery is detected quickly without repeated multi-second connection attempts.\n",
    "- After `ENETUNREACH`/`EHOSTUNREACH`, switch to short raw TCP probes of LG ports 3001/3000 before resuming full TLS/WebSocket negotiation, so Remote LAN recovery is detected quickly without repeated multi-second connection attempts.\n- Detect LAN-path outages even when `LGDevice.connect()` logs and absorbs the connector exception; a failed reconnect now checks endpoint reachability directly before applying the normal 5-second backoff.\n",
)
