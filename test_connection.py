# pylint: skip-file
# flake8: noqa
import asyncio
import logging
import sys
from types import SimpleNamespace
from typing import Any

sys.path.insert(1, "src")

from aiowebostv import WebOsClient, WebOsTvState
from aiowebostv import endpoints as ep
from aiowebostv.exceptions import WebOsTvResponseTypeError
from rich import print_json
from ucapi import StatusCodes
from ucapi.select import Attributes as SelectAttributes

from config import LGConfigDevice
from const import LGSelects
from lg import Events, LGDevice

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)

# 55
# address = "192.168.1.41"
# mac_address = "04:4e:af:00:85:92"
# pairing_key = "4843d0b3a3ded816bcba7fce3f3a5ce1"

# 77
address = "192.168.1.118"
mac_address = "4c:ba:d7:64:8c:b0"
# mac_address2 = "ac:5a:f0:97:66:76"
pairing_key = "08430cefd592affb85fd56ffb31cd489"


async def pair():
    _pairing_lg_tv = WebOsClient(address)
    await _pairing_lg_tv.connect()
    key = _pairing_lg_tv.client_key
    _LOG.debug("Pairing key : %s", key)


async def confirm_pairing(client: LGDevice):
    # Validate pairing key (77)
    # await client.button("ENTER")

    # Validate pairing key (55)
    await client.button("RIGHT")
    await client.button("ENTER")


async def _on_state_changed(state: WebOsTvState):
    print("State changed")
    if state.power_state:
        print("Power state")
        print_json(data=state.power_state)
    if state.media_state:
        print("Media state")
        print_json(data=state.media_state)
    if state.channel_info:
        print("Channel info")
        print_json(data=state.channel_info)
    # ...


async def on_device_update(device_id: str, update: dict[str, Any] | None) -> None:
    print_json(data=update)


async def direct_connect():
    tv: WebOsClient = WebOsClient(host=address, client_key=pairing_key)
    await tv.connect()
    await asyncio.sleep(50)


def test_picture_mode_selection_uses_display_name():
    """Keep the selector value aligned with its human-readable options."""

    class FakeTv:
        def __init__(self):
            self.requests = []

        async def request(self, endpoint, payload=None):
            self.requests.append((endpoint, payload))
            if endpoint == ep.GET_SYSTEM_SETTINGS:
                return {"returnValue": True, "settings": {"pictureMode": "hdrStandard"}}
            return {"returnValue": True}

    class FakeEvents:
        def __init__(self):
            self.updates = []

        def emit(self, event, device_id, update):
            self.updates.append((event, device_id, update))

    async def scenario():
        client = object.__new__(LGDevice)
        client._device_config = SimpleNamespace(address="test-tv")
        client._tv = FakeTv()
        client._picture_modes = {"Hdr Standard": "hdrStandard"}
        client._picture_mode = "Cinema"
        client._picture_mode_direct_write_supported = None
        client._background_tasks = set()
        client.events = FakeEvents()
        client.id = "test-device"

        result = await LGDevice.set_picture_mode.__wrapped__(client, "Hdr Standard")
        pending = list(client._background_tasks)
        if pending:
            await asyncio.gather(*pending)

        assert result == StatusCodes.OK
        assert client._tv.requests[0] == (
            "settings/setSystemSettings",
            {"category": "picture", "settings": {"pictureMode": "hdrStandard"}},
        )
        assert client.picture_mode == "Hdr Standard"
        current_options = [
            update[LGSelects.SELECT_PICTURE_MODE][SelectAttributes.CURRENT_OPTION]
            for _, _, update in client.events.updates
        ]
        assert current_options
        assert set(current_options) == {"Hdr Standard"}

    asyncio.run(scenario())


def test_picture_mode_selection_falls_back_when_write_settings_is_denied():
    """Use the Luna alert path when direct settings writes lack permission."""

    class FakeTv:
        def __init__(self):
            self.requests = []

        async def request(self, endpoint, payload=None):
            self.requests.append((endpoint, payload))
            if endpoint == "settings/setSystemSettings":
                raise WebOsTvResponseTypeError(
                    {
                        "type": "error",
                        "id": 14,
                        "error": "401 insufficient permissions",
                        "payload": {},
                    }
                )
            if endpoint == ep.CREATE_ALERT:
                return {"returnValue": True, "alertId": "picture-mode-alert"}
            if endpoint == ep.GET_SYSTEM_SETTINGS:
                return {"returnValue": True, "settings": {"pictureMode": "cinema"}}
            return {"returnValue": True}

    class FakeEvents:
        def emit(self, _event, _device_id, _update):
            pass

    async def scenario():
        client = object.__new__(LGDevice)
        client._device_config = SimpleNamespace(address="test-tv")
        client._tv = FakeTv()
        client._picture_modes = {"Cinema": "cinema"}
        client._picture_mode = "Vivid"
        client._picture_mode_direct_write_supported = None
        client._background_tasks = set()
        client.events = FakeEvents()
        client.id = "test-device"

        result = await LGDevice.set_picture_mode.__wrapped__(client, "Cinema")
        pending = list(client._background_tasks)
        if pending:
            await asyncio.gather(*pending)

        assert result == StatusCodes.OK
        assert client._picture_mode_direct_write_supported is False
        assert [request[0] for request in client._tv.requests[:3]] == [
            "settings/setSystemSettings",
            ep.CREATE_ALERT,
            ep.CLOSE_ALERT,
        ]
        alert_payload = client._tv.requests[1][1]
        assert alert_payload["buttons"][0] == {
            "label": "",
            "onClick": "luna://com.webos.settingsservice/setSystemSettings",
            "params": {
                "category": "picture",
                "settings": {"pictureMode": "cinema"},
            },
        }
        assert client._tv.requests[2][1] == {"alertId": "picture-mode-alert"}

    asyncio.run(scenario())


async def main():
    _LOG.debug("Start connection")
    # await pair()
    # exit(0)
    client = LGDevice(
        device_config=LGConfigDevice(
            id="deviceid",
            name="LG TV",
            address=address,
            mac_address=mac_address,
            mac_address2=None,
            key=pairing_key,
            interface="0.0.0.0",
            broadcast=None,  # or network mask like 192.168.1.255
            wol_port=9,
            log=True,
        )
    )
    await client._tv.register_state_update_callback(_on_state_changed)
    client.events.on(Events.UPDATE, on_device_update)
    await client.power_on()
    await client.connect()

    print_json(
        data=await client._tv.request(
            ep.GET_CONFIGS, payload={"configNames": ["tv.model.*"]}
        )
    )

    # print_json(data=await client.get_system_settings("picture", keys=["pictureModes"]))
    # print_json(data=await client._tv.get_power_state())
    # print_json(data=client._tv.tv_info.system)
    # print_json(data=await client._tv.get_software_info())
    # print_json(data=await client._tv.get_power_state())
    # print_json(data=await client._tv.get_current_app())
    # print_json(data=await client._tv.get_media_foreground_app())
    # print_json(data=await client._tv.get_audio_status())
    # print_json(data=await client._tv.get_input())

    # print_json(
    #     data=await client.client.request(
    #         "settings/getSystemSettings", {"category": "picture", "keys": ["pictureModes"]}
    #     )
    # )

    await asyncio.sleep(50)
    # print_json(data=await client._tv.get_power_state())
    # await asyncio.sleep(120)
    # state = client._tv.tv_state
    # await _on_state_changed(state)
    # await asyncio.sleep(10)
    # await client.button("FASTFORWARD")
    # await asyncio.sleep(5)
    # await client.button("PLAY PAUSE")
    # await client.play_pause()
    # await asyncio.sleep(60)

    # await asyncio.sleep(5)
    # await client.custom_command("channel '101'")
    # await client.custom_command("picture backlight -10")
    # results = await client.client.request("settings/getSystemSettings", {'category': 'picture', 'keys':['backlight']})
    # results = await client.client.request("settings/getSystemSettings", {'category': 'picture', 'keys': ['contrast', 'backlight', 'brightness', 'color']})
    # print_json(data=results)
    # await client.custom_command("system.launcher/launch {'id': 'com.webos.app.screensaver'}")
    # await client.custom_command("system.launcher/close {'id': 'com.webos.app.screensaver'}")
    # await client.custom_notification("com.webos.settingsservice/setSystemSettings {'category': 'picture', 'settings': {'pictureMode': 'expert2'}}")
    exit(0)
    # sources = client.source_list
    # print(sources)
    #
    # await client.select_source("HDMI1")
    # for app in client._tv.tv_state.apps.values():
    #     print(json.dumps(app, indent=3))
    # for source in client._tv.tv_state.inputs.values():
    #     print(json.dumps(source, indent=3))

    # power_state = await client._tv.get_power_state()
    # _LOG.debug("Power state %s", power_state)
    # tv_info = client._tv.tv_info
    # _LOG.debug("TV Info %s", tv_info)

    # Confirm pairing prompt
    await confirm_pairing(client)


if __name__ == "__main__":
    _LOG = logging.getLogger(__name__)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    logging.basicConfig(handlers=[ch])
    logging.getLogger("client").setLevel(logging.DEBUG)
    logging.getLogger("lg").setLevel(logging.DEBUG)
    logging.getLogger("aiowebostv").setLevel(logging.DEBUG)
    logging.getLogger(__name__).setLevel(logging.DEBUG)
    _LOOP.run_until_complete(main())
    # _LOOP.run_until_complete(direct_connect())
    _LOOP.run_forever()
