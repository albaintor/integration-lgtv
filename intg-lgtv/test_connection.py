import asyncio
import logging
import sys

from aiowebostv import WebOsClient

from lg import LGDevice
from config import LGConfigDevice

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)

address="192.168.1.67"
mac_address="4c:ba:d7:64:8c:b0"
pairing_key="88de3f23b5cc6bf5d8c8c37086cdad6d"

async def pair():
    _pairing_lg_tv = WebOsClient(address)
    await _pairing_lg_tv.connect()
    key = _pairing_lg_tv.client_key
    _LOG.debug("Pairing key : %s", key)

async def main():
    _LOG.debug("Start connection")
    #await pair()
    client = LGDevice(device_config=
                      LGConfigDevice(id="deviceid", name="LG Soundbar", address=address,
                                     mac_address=mac_address, mac_address2=None,
                                     key=pairing_key, interface="0.0.0.0", broadcast=None, wol_port=9))
    await client.connect()
    power_state = await client._tv.get_power_state()
    _LOG.debug("Power state %s", power_state)
    tv_info = client._tv.tv_info
    _LOG.debug("TV Info %s", tv_info)

    #await client.select_source("HDMI")
    #_LOG.debug("INFO %s %s", client.volume, client.attributes)

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
