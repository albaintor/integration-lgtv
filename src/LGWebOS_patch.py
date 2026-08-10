"""Make aiowebostv work on webOS 26 (LG firmware 43.00.92+).

webOS 26 changed the SSAP pairing handshake. The "LG Remote App" manifest that
aiowebostv sends (appId ``com.lge.test`` plus a baked-in LG signature) is now
**blacklisted**: the TV still issues a client-key, but grants the app **no
permissions at all** — every request and subscription, even ``getPowerState``
and ``getVolume``, answers ``401 insufficient permissions (not registered)``.
The integration "connects" but can read nothing and control nothing.

The fix (same approach LGTV Companion uses, see JPersson77/LGTVCompanion#351)
is to register with a **generic manifest** that drops the blacklisted LG
identity/signature. After re-pairing with it, the TV grants normal permissions
again and power/volume/source/app/media controls work.

This module patches aiowebostv at runtime to:

1. ``registration_msg`` -> send a generic manifest instead of the LG one. THE
   key fix; requires a one-time re-pair to obtain a permissioned client-key.
2. ``_create_input_ws`` / ``_rx_msgs_input_ws`` -> tolerate the pointer input
   socket still being denied (remote button/pointer emulation is removed by LG
   on webOS 26 and cannot be restored).
3. ``get_software_info`` / ``subscribe`` -> never abort connect on a 401.
4. ``callback_handler`` -> a state callback that chokes on an unexpected
   payload must not stall the connection.

Design goals: self-disable on any aiowebostv newer than the affected versions
(the official fix takes over), and never raise (must not break HA startup).
Tracking: home-assistant/core#172703.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from contextlib import suppress

_LOGGER = logging.getLogger(__name__)

_PATCH_FLAG = "_webos26_input_patch_applied"
# aiowebostv releases that still send the blacklisted LG Remote App manifest.
# On any newer (presumed-fixed) version the patch deactivates itself.
_MAX_AFFECTED = (0, 7, 5)
# Hosts we've already logged the pointer-socket loss for (avoid repeat spam).
_warned_hosts: set[str] = set()

# Generic registration manifest: same permission set aiowebostv requests, but
# without the blacklisted LG identity (appId "com.lge.test" / "LG Remote App")
# and without the LG signature block. webOS 26 grants permissions to this where
# it denies the LG one. Pairing with it requires a fresh prompt on the TV.
_GENERIC_REGISTRATION = {
    "type": "register",
    "id": "register_0",
    "payload": {
        "forcePairing": False,
        "pairingType": "PROMPT",
        "manifest": {
            "manifestVersion": 1,
            "appVersion": "1.0",
            "signed": {
                "created": "20240101",
                "appId": "com.unfoldedcircle.webostv",
                "localizedAppNames": {"": "Unfolded Circle Remote"},
                "localizedVendorNames": {"": "Unfolded Circle Remote"},
                "permissions": [
                    "TEST_SECURE",
                    "CONTROL_INPUT_TEXT",
                    "CONTROL_MOUSE_AND_KEYBOARD",
                    "READ_INSTALLED_APPS",
                    "READ_LGE_SDX",
                    "READ_NOTIFICATIONS",
                    "SEARCH",
                    "WRITE_SETTINGS",
                    "WRITE_NOTIFICATION_ALERT",
                    "CONTROL_POWER",
                    "READ_CURRENT_CHANNEL",
                    "READ_RUNNING_APPS",
                    "READ_UPDATE_INFO",
                    "UPDATE_FROM_REMOTE_APP",
                    "READ_LGE_TV_INPUT_EVENTS",
                    "READ_TV_CURRENT_TIME",
                ],
                "serial": "unfoldedcircle-webostv",
            },
            "permissions": [
                "LAUNCH",
                "LAUNCH_WEBAPP",
                "APP_TO_APP",
                "CLOSE",
                "TEST_OPEN",
                "TEST_PROTECTED",
                "CONTROL_AUDIO",
                "CONTROL_DISPLAY",
                "CONTROL_INPUT_JOYSTICK",
                "CONTROL_INPUT_MEDIA_RECORDING",
                "CONTROL_INPUT_MEDIA_PLAYBACK",
                "CONTROL_INPUT_TV",
                "CONTROL_POWER",
                "CONTROL_TV_SCREEN",
                "READ_APP_STATUS",
                "READ_CURRENT_CHANNEL",
                "READ_INPUT_DEVICE_LIST",
                "READ_NETWORK_STATE",
                "READ_RUNNING_APPS",
                "READ_TV_CHANNEL_LIST",
                "WRITE_NOTIFICATION_TOAST",
                "READ_POWER_STATE",
                "READ_COUNTRY_INFO",
                "CONTROL_INPUT_TEXT",
                "CONTROL_MOUSE_AND_KEYBOARD",
                "READ_INSTALLED_APPS",
                "READ_SETTINGS",
            ],
        },
    },
}


def _version_tuple(value: str) -> tuple[int, ...]:
    """Best-effort parse of a dotted version string into a comparable tuple."""
    parts: list[int] = []
    for chunk in str(value).split("."):
        digits = ""
        for char in chunk:
            if char.isdigit():
                digits += char
            else:
                break
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def apply_patch() -> None:
    """Idempotently patch WebOsClient. Never raises."""
    try:
        import aiowebostv
        from aiowebostv import WebOsClient
        from aiowebostv.exceptions import WebOsTvResponseTypeError

        if getattr(WebOsClient, _PATCH_FLAG, False):
            return

        version = getattr(aiowebostv, "__version__", "0")
        if _version_tuple(version) > _MAX_AFFECTED:
            _LOGGER.info(
                "aiowebostv %s is newer than the affected versions; webOS 26 "
                "patch not applied (official fix presumably present)",
                version,
            )
            setattr(WebOsClient, _PATCH_FLAG, True)
            return

        required = (
            "registration_msg",
            "_create_input_ws",
            "_rx_msgs_input_ws",
            "get_software_info",
            "subscribe",
            "callback_handler",
        )
        missing = [name for name in required if not hasattr(WebOsClient, name)]
        if missing:
            _LOGGER.warning(
                "aiowebostv %s missing %s; webOS 26 patch skipped",
                version,
                missing,
            )
            return

        def _is_permission_denied(ex: Exception) -> bool:
            msg = str(ex).lower()
            return "401" in msg or "insufficient permissions" in msg

        orig_create_input_ws = WebOsClient._create_input_ws
        orig_rx_msgs_input_ws = WebOsClient._rx_msgs_input_ws
        orig_get_software_info = WebOsClient.get_software_info
        orig_subscribe = WebOsClient.subscribe

        def registration_msg(self):  # type: ignore[no-untyped-def]
            handshake = copy.deepcopy(_GENERIC_REGISTRATION)
            if getattr(self, "client_key", None) is not None:
                handshake["payload"]["client-key"] = self.client_key
            return handshake

        async def _create_input_ws(self):  # type: ignore[no-untyped-def]
            try:
                return await orig_create_input_ws(self)
            except WebOsTvResponseTypeError as ex:
                if not _is_permission_denied(ex):
                    raise
                host = getattr(self, "host", "?")
                if host not in _warned_hosts:
                    _warned_hosts.add(host)
                    _LOGGER.warning(
                        "webOS 26 patch: TV %s denied the pointer input socket; "
                        "remote button/pointer commands are unavailable, all "
                        "other controls work normally",
                        host,
                    )
                return None

        async def _rx_msgs_input_ws(self, web_socket):  # type: ignore[no-untyped-def]
            if web_socket is None:
                # No input socket: block until cancelled during tear-down so
                # connect_handler's asyncio.wait(FIRST_COMPLETED) is driven only
                # by the main socket and the connection stays up.
                await asyncio.Event().wait()
                return
            return await orig_rx_msgs_input_ws(self, web_socket)

        async def get_software_info(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            try:
                return await orig_get_software_info(self, *args, **kwargs)
            except WebOsTvResponseTypeError as ex:
                if not _is_permission_denied(ex):
                    raise
                _LOGGER.debug(
                    "webOS 26 patch: software info denied on %s; continuing",
                    getattr(self, "host", "?"),
                )
                return {}

        async def subscribe(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            try:
                return await orig_subscribe(self, *args, **kwargs)
            except WebOsTvResponseTypeError as ex:
                if not _is_permission_denied(ex):
                    raise
                _LOGGER.debug(
                    "webOS 26 patch: a state subscription was denied on %s; "
                    "continuing without it",
                    getattr(self, "host", "?"),
                )
                return {}

        @staticmethod
        async def callback_handler(queue, callback, future):  # type: ignore[no-untyped-def]
            # webOS 26 can send altered subscription payloads that some state
            # callbacks can't parse. In the stock handler a callback exception
            # skips future.set_result(), so the subscription's future never
            # resolves and the whole connect hangs. Swallow callback errors so
            # the future always resolves and the connection completes.
            with suppress(asyncio.CancelledError):
                while True:
                    msg = await queue.get()
                    payload = msg.get("payload")
                    try:
                        await callback(payload)
                    except Exception:  # noqa: BLE001
                        _LOGGER.debug(
                            "webOS 26 patch: subscription callback failed on "
                            "%s, ignoring payload",
                            getattr(callback, "__name__", callback),
                            exc_info=True,
                        )
                    if not future.done():
                        future.set_result(msg)

        WebOsClient.registration_msg = registration_msg  # type: ignore[method-assign]
        WebOsClient._create_input_ws = _create_input_ws  # type: ignore[method-assign]
        WebOsClient._rx_msgs_input_ws = _rx_msgs_input_ws  # type: ignore[method-assign]
        WebOsClient.get_software_info = get_software_info  # type: ignore[method-assign]
        WebOsClient.subscribe = subscribe  # type: ignore[method-assign]
        WebOsClient.callback_handler = callback_handler  # type: ignore[method-assign]
        setattr(WebOsClient, _PATCH_FLAG, True)
        _LOGGER.info(
            "Applied webOS 26 patch (generic manifest + 401 tolerance) to "
            "aiowebostv %s",
            version,
        )
    except Exception:  # noqa: BLE001 - must never break HA startup
        _LOGGER.exception("Failed to apply webOS 26 input-socket patch")
