from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    if old not in text:
        raise SystemExit(f"Expected block not found in {path}")
    file.write_text(text.replace(old, new, 1))


replace_once(
    "src/connection_recovery.py",
    '''LG_HEARTBEAT = 30.0

# ucapi 0.7.x does not expose WIFI_CHANGE yet, but newer Remote firmware can
''',
    '''LG_HEARTBEAT = 30.0

# After ENETUNREACH/EHOSTUNREACH, avoid repeatedly paying the full LG
# TCP/TLS/WebSocket timeout while the Remote LAN route is still recovering.
# Short raw TCP probes detect when either LG endpoint becomes reachable again.
LG_NETWORK_PROBE_TIMEOUT = 0.5
LG_NETWORK_PROBE_INTERVAL = 0.5
LG_NETWORK_RECOVERY_WINDOW = 5.0
LG_NETWORK_PATH_ERRNOS = {errno.ENETUNREACH, errno.EHOSTUNREACH}

# ucapi 0.7.x does not expose WIFI_CHANGE yet, but newer Remote firmware can
''',
)

replace_once(
    "src/connection_recovery.py",
    '''        _LOG.debug(
            "[%s] LG WOL sent during reconnect: %s",
            self._device_config.address,
            reason,
        )
        return True

    def request_reconnect(
''',
    '''        _LOG.debug(
            "[%s] LG WOL sent during reconnect: %s",
            self._device_config.address,
            reason,
        )
        return True

    @staticmethod
    def _network_path_errno(ex: BaseException) -> int | None:
        """Return ENETUNREACH/EHOSTUNREACH found in a wrapped connection error."""
        current: BaseException | None = ex
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            os_error = getattr(current, "os_error", None)
            for candidate in (current, os_error):
                error_number = getattr(candidate, "errno", None)
                if error_number in LG_NETWORK_PATH_ERRNOS:
                    return error_number

            nested = current.__cause__ or current.__context__
            current = nested if isinstance(nested, BaseException) else None

        return None

    async def _network_path_ready(self) -> bool:
        """Probe LG TCP endpoints without starting TLS/WebSocket negotiation."""
        for port in (WSS_PORT, WS_PORT):
            writer: asyncio.StreamWriter | None = None
            try:
                async with asyncio.timeout(LG_NETWORK_PROBE_TIMEOUT):
                    _, writer = await asyncio.open_connection(
                        self._device_config.address,
                        port,
                    )
            except TimeoutError:
                continue
            except OSError as ex:
                if ex.errno in LG_NETWORK_PATH_ERRNOS:
                    continue

                # ECONNREFUSED (or another immediate host response) proves that
                # the LAN path is back. Let the normal LG negotiation decide
                # whether WSS/3001 or legacy WS/3000 should be used.
                _LOG.debug(
                    "[%s] LG network probe reached port %s with errno %s; "
                    "resume full connection",
                    self._device_config.address,
                    port,
                    ex.errno,
                )
                return True
            else:
                writer.close()
                with suppress(Exception):
                    await writer.wait_closed()
                return True
            finally:
                if writer is not None and not writer.is_closing():
                    writer.close()

        return False

    async def _wait_for_network_path(self) -> bool:
        """Poll the LAN path quickly for one bounded recovery window."""
        started = time.monotonic()
        deadline = started + LG_NETWORK_RECOVERY_WINDOW
        _LOG.debug(
            "[%s] LG network recovery mode: probing ports %s/%s every %.1fs",
            self._device_config.address,
            WSS_PORT,
            WS_PORT,
            LG_NETWORK_PROBE_INTERVAL,
        )

        while True:
            probe_started = time.monotonic()
            if await self._network_path_ready():
                _LOG.debug(
                    "[%s] LG network path recovered after %.3fs; "
                    "resume WebSocket/TLS connection",
                    self._device_config.address,
                    time.monotonic() - started,
                )
                return True

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _LOG.debug(
                    "[%s] LG network path still unavailable after %.1fs",
                    self._device_config.address,
                    LG_NETWORK_RECOVERY_WINDOW,
                )
                return False

            probe_elapsed = time.monotonic() - probe_started
            delay = min(
                max(0.0, LG_NETWORK_PROBE_INTERVAL - probe_elapsed),
                remaining,
            )
            if delay > 0:
                await asyncio.sleep(delay)

    def request_reconnect(
''',
)

replace_once(
    "src/connection_recovery.py",
    '''    async def _connect_loop(self) -> None:
        """Reconnect serially with a stable backoff between attempts.

        The retry count is local so button presses cannot reset an active loop
        through lg.retry_call_command(). This mirrors LG ConnectSDK's approach:
        an existing connection attempt stays authoritative until it completes.
        """
        retry_count = 0
        try:
            while True:
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
                    _LOG.debug(
                        "[%s] LG TV connect task cancelled",
                        self._device_config.address,
                    )
                    break
                # pylint: disable=W0718
                except Exception as ex:
                    _LOG.warning(
                        "[%s] LG TV connection failed %s",
                        self._device_config.address,
                        ex,
                    )

                retry_count += 1
                self._reconnect_retry = retry_count
                self._attr_state = States.OFF
                if retry_count > lg.CONNECTION_RETRIES:
                    _LOG.debug(
                        "[%s] LG not connected abort retries",
                        self._device_config.address,
                    )
                    break

                if self._retry_wakeonlan:
                    self._try_wakeonlan(f"retry {retry_count}")

                _LOG.debug(
                    "[%s] LG not connected, retry %s / %s in %ss",
                    self._device_config.address,
                    retry_count,
                    lg.CONNECTION_RETRIES,
                    lg.DEFAULT_TIMEOUT,
                )
                await asyncio.sleep(lg.DEFAULT_TIMEOUT)
        except CancelledError:
            _LOG.debug("[%s] LG TV connect task cancelled", self._device_config.address)
        finally:
            self._retry_wakeonlan = False
            self._connect_task = None
            self._reconnect_retry = 0
''',
    '''    async def _connect_loop(self) -> None:
        """Reconnect serially, using fast LAN probes after route failures.

        The retry count is local so button presses cannot reset an active loop
        through lg.retry_call_command(). Once ENETUNREACH/EHOSTUNREACH is seen,
        raw TCP probes replace expensive TLS/WebSocket attempts until the Remote
        can reach the TV again. Wake-on-LAN remains armed throughout recovery.
        """
        retry_count = 0
        network_recovery = False
        try:
            while True:
                if network_recovery:
                    if await self._wait_for_network_path():
                        network_recovery = False
                    else:
                        retry_count += 1
                        self._reconnect_retry = retry_count
                        self._attr_state = States.OFF
                        if retry_count > lg.CONNECTION_RETRIES:
                            _LOG.debug(
                                "[%s] LG not connected abort retries",
                                self._device_config.address,
                            )
                            break

                        if self._retry_wakeonlan:
                            self._try_wakeonlan(
                                f"network recovery {retry_count}"
                            )
                        continue

                network_path_errno: int | None = None
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
                    _LOG.debug(
                        "[%s] LG TV connect task cancelled",
                        self._device_config.address,
                    )
                    break
                # pylint: disable=W0718
                except Exception as ex:
                    network_path_errno = self._network_path_errno(ex)
                    _LOG.warning(
                        "[%s] LG TV connection failed %s",
                        self._device_config.address,
                        ex,
                    )
                    if network_path_errno is not None:
                        _LOG.debug(
                            "[%s] LG network path failure errno=%s; "
                            "switch to fast TCP probes",
                            self._device_config.address,
                            network_path_errno,
                        )

                retry_count += 1
                self._reconnect_retry = retry_count
                self._attr_state = States.OFF
                if retry_count > lg.CONNECTION_RETRIES:
                    _LOG.debug(
                        "[%s] LG not connected abort retries",
                        self._device_config.address,
                    )
                    break

                if self._retry_wakeonlan:
                    self._try_wakeonlan(f"retry {retry_count}")

                if network_path_errno is not None:
                    network_recovery = True
                    continue

                _LOG.debug(
                    "[%s] LG not connected, retry %s / %s in %ss",
                    self._device_config.address,
                    retry_count,
                    lg.CONNECTION_RETRIES,
                    lg.DEFAULT_TIMEOUT,
                )
                await asyncio.sleep(lg.DEFAULT_TIMEOUT)
        except CancelledError:
            _LOG.debug("[%s] LG TV connect task cancelled", self._device_config.address)
        finally:
            self._retry_wakeonlan = False
            self._connect_task = None
            self._reconnect_retry = 0
''',
)

replace_once(
    "test/test_connection_recovery_profile.py",
    '''        self.assertTrue(device._retry_wakeonlan)
        device.wakeonlan.assert_called_once_with()
        await active_task


if __name__ == "__main__":
''',
    '''        self.assertTrue(device._retry_wakeonlan)
        device.wakeonlan.assert_called_once_with()
        await active_task

    async def test_host_unreachable_switches_to_fast_network_probe(self) -> None:
        device = object.__new__(LGDevice)
        device._device_config = SimpleNamespace(address="test-tv")
        device._retry_wakeonlan = False
        device._connect_task = None
        device._reconnect_retry = 0
        device._attr_state = States.OFF
        device._tv = SimpleNamespace(tv_state=SimpleNamespace(is_on=True))
        device.connect = AsyncMock(
            side_effect=[
                OSError(errno.EHOSTUNREACH, "No route to host"),
                None,
            ]
        )
        device._wait_for_network_path = AsyncMock(return_value=True)
        device._update_picture_modes = MagicMock()

        await device._connect_loop()

        self.assertEqual(device.connect.await_count, 2)
        device._wait_for_network_path.assert_awaited_once_with()
        device._update_picture_modes.assert_called_once_with()


if __name__ == "__main__":
''',
)

replace_once(
    "test/test_connection_recovery_profile.py",
    '''from lg_tcp_connector import LGDiagnosticTCPConnector  # noqa: E402
''',
    '''from lg_tcp_connector import LGDiagnosticTCPConnector  # noqa: E402
from ucapi.media_player import States  # noqa: E402
''',
)

replace_once(
    "CHANGELOG.md",
    '''- Make Wake-on-LAN best-effort during Remote wake: a transient `ENETUNREACH` can no longer terminate the reconnect loop, and `EXIT_STANDBY` keeps WOL armed for subsequent retries until the TV becomes reachable.
''',
    '''- Make Wake-on-LAN best-effort during Remote wake: a transient `ENETUNREACH` can no longer terminate the reconnect loop, and `EXIT_STANDBY` keeps WOL armed for subsequent retries until the TV becomes reachable.
- After `ENETUNREACH`/`EHOSTUNREACH`, switch to short raw TCP probes of LG ports 3001/3000 before resuming full TLS/WebSocket negotiation, so Remote LAN recovery is detected quickly without repeated multi-second connection attempts.
''',
)
