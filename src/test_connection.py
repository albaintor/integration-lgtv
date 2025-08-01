# pylint: skip-file
# flake8: noqa
import asyncio
import json
import logging
import sys

from aiowebostv import WebOsClient

from config import LGConfigDevice
from lg import LGDevice

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)

# 55
address = "192.168.1.41"
mac_address = "04:4e:af:00:85:92"
pairing_key = "4843d0b3a3ded816bcba7fce3f3a5ce1"

# 77
# address = "192.168.1.118"
# mac_address = "4c:ba:d7:64:8c:b0"
# pairing_key = "88de3f23b5cc6bf5d8c8c37086cdad6d"


async def pair():
    _pairing_lg_tv = WebOsClient(address)
    await _pairing_lg_tv.connect()
    key = _pairing_lg_tv.client_key
    _LOG.debug("Pairing key : %s", key)


async def main():
    _LOG.debug("Start connection")
    # await pair()
    # exit(0)
    client = LGDevice(
        device_config=LGConfigDevice(
            id="deviceid",
            name="LG Soundbar",
            address=address,
            mac_address=mac_address,
            mac_address2=None,
            key=pairing_key,
            interface="0.0.0.0",
            broadcast=None,
            wol_port=9,
        )
    )
    # await client.power_on()
    # await client.connect()
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

    # Validate pairing key (77)
    # await client.button("ENTER")

    # Validate pairing key (55)
    await client.button("RIGHT")
    await client.button("ENTER")


if __name__ == "__main__":
    _LOG = logging.getLogger(__name__)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    logging.basicConfig(handlers=[ch])
    logging.getLogger("client").setLevel(logging.DEBUG)
    logging.getLogger("lg").setLevel(logging.DEBUG)
    logging.getLogger(__name__).setLevel(logging.DEBUG)
    _LOOP.run_until_complete(main())
    _LOOP.run_forever()
