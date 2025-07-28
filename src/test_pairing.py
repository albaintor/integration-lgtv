# pylint: skip-file
# flake8: noqa
import asyncio
import json
import logging
import sys

from aiowebostv import WebOsClient
from argparse import ArgumentParser

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


async def pair(address: str) -> tuple[WebOsClient, str]:
    _pairing_lg_tv = WebOsClient(address)
    await _pairing_lg_tv.connect()
    key = _pairing_lg_tv.client_key
    return _pairing_lg_tv, key


async def main():
    parser = ArgumentParser(description="Pair and test connection to LG TV"
                                        "(example : python -address 192.168.1.10)")
    parser.add_argument("-address", type=str, help="IP address of the LG TV", required=True)
    args = parser.parse_args()
    print("Trying to pair TV with address", args.address)

    try:
        _LOG.debug("Start connection")
        (client, key) = await pair(args.address)
        _LOG.debug("Success getting pairing key : %s", key)

        # Debug LG info : apps, inputs, power state
        for app in client.tv_state.apps.values():
            print(json.dumps(app, indent=3))
        for source in client.tv_state.inputs.values():
            print(json.dumps(source, indent=3))

        power_state = await client.get_power_state()
        _LOG.debug("Power state %s", power_state)
        tv_info = client.tv_info
        _LOG.debug("TV Info %s", tv_info)
        exit(0)
    except Exception as ex:
        _LOG.error("Error during connection : %s", ex)
        exit(2)


if __name__ == "__main__":
    _LOG = logging.getLogger(__name__)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    logging.basicConfig(handlers=[ch])
    logging.getLogger("aiowebostv").setLevel(logging.DEBUG)
    logging.getLogger("webos_client").setLevel(logging.DEBUG)
    logging.getLogger(__name__).setLevel(logging.DEBUG)
    _LOOP.run_until_complete(main())
    _LOOP.run_forever()
