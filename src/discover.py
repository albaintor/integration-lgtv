#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""This module implements a discovery function for LG TV."""

import asyncio
import logging
import re
import socket
import sys
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

import httpx
from defusedxml.ElementTree import fromstring
from httpx import Response

_LOGGER = logging.getLogger(__name__)

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900
SSDP_MX = 2
SSDP_TARGET = (SSDP_ADDR, SSDP_PORT)
SSDP_ST_1 = "ssdp:all"
SSDP_ST_2 = "upnp:rootdevice"
SSDP_ST_4 = "urn:schemas-upnp-org:device:Basic:1"
SSDP_ST_3 = "urn:lge-com:service:webos-second-screen:1"

SSDP_ST_LIST = (SSDP_ST_1, SSDP_ST_2, SSDP_ST_3, SSDP_ST_4)

SSDP_LOCATION_PATTERN = re.compile(r"(?<=Location:\s).+?(?=\r)", re.IGNORECASE)

SCPD_XMLNS = "{urn:schemas-upnp-org:device-1-0}"
SCPD_DEVICE = f"{SCPD_XMLNS}device"
SCPD_DEVICELIST = f"{SCPD_XMLNS}deviceList"
SCPD_DEVICETYPE = f"{SCPD_XMLNS}deviceType"
SCPD_MANUFACTURER = f"{SCPD_XMLNS}manufacturer"
SCPD_MODELNAME = f"{SCPD_XMLNS}modelName"
SCPD_SERIALNUMBER = f"{SCPD_XMLNS}serialNumber"
SCPD_FRIENDLYNAME = f"{SCPD_XMLNS}friendlyName"
SCPD_PRESENTATIONURL = f"{SCPD_XMLNS}presentationURL"
SCPD_WIFIMAC = f"{SCPD_XMLNS}wifiMac"
SCPD_WIREDMAC = f"{SCPD_XMLNS}wiredMac"

SUPPORTED_DEVICETYPES = [
    "urn:schemas-upnp-org:device:Basic:1",
    "urn:dial-multiscreen-org:service:dial:1",
    "urn:lge:device:tv:1",
    "urn:schemas-upnp-org:device:MediaRenderer:1",
]

SUPPORTED_MANUFACTURERS = ["LG Electronics", "LG"]


def ssdp_request(ssdp_st: str, ssdp_mx: float = SSDP_MX) -> bytes:
    """Return request bytes for given st and mx."""
    return "\r\n".join(
        [
            "M-SEARCH * HTTP/1.1",
            f"ST: {ssdp_st}",
            f"MX: {ssdp_mx:d}",
            'MAN: "ssdp:discover"',
            f"HOST: {SSDP_ADDR}:{SSDP_PORT}",
            "",
            "",
        ]
    ).encode("utf-8")


def get_best_family(*address):
    """Backport of private `http.server._get_best_family`."""
    family = socket.AF_INET if sys.platform == "win32" else 0

    infos = socket.getaddrinfo(
        *address,
        family=family,
        type=socket.SOCK_STREAM,
        flags=socket.AI_PASSIVE,
    )
    family, _type, _proto, _canonname, sockaddr = next(iter(infos))
    return family, sockaddr


def get_local_ips() -> List[str]:
    """Get IPs of local network adapters."""
    return [i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None)]


async def async_identify_lg_devices() -> List[Dict]:
    """
    Identify LG using SSDP and SCPD queries.

    Returns a list of dictionaries which includes all discovered LG
    devices with keys "host", "modelName", "friendlyName", "presentationURL".
    """
    # Sending SSDP broadcast message to get resource urls from devices
    urls = await async_send_ssdp_broadcast()

    # Check which responding device is a Orange TV device and prepare output
    devices = []

    for url in urls:
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(url, timeout=5.0)
                res.raise_for_status()
        except httpx.HTTPError:
            continue
        else:
            try:
                device = evaluate_scpd_xml(url, res)
                if device is not None:
                    devices.append(device)
            # pylint: disable = W0718
            except Exception as ex:
                _LOGGER.error("Error while discovering %s", ex)

    unique_devices: dict[str, dict[str, any]] = {}
    for device in devices:
        unique_device = unique_devices.get(device.get("host"), None)
        if not unique_device:
            unique_devices[device.get("host")] = device
            continue
        if device.get("wiredMac"):
            unique_device["wiredMac"] = device.get("wiredMac")
        if device.get("wifiMac"):
            unique_device["wifiMac"] = device.get("wifiMac")

    return list(unique_devices.values())


async def async_send_ssdp_broadcast() -> Set[str]:
    """
    Send SSDP broadcast messages to discover UPnP devices.

    Returns a set of SCPD XML resource urls for all discovered devices.
    """
    # Send up to three different broadcast messages
    ips = get_local_ips()
    # Prepare output of responding devices
    urls = set()

    tasks = []
    for ip_addr in ips:
        tasks.append(async_send_ssdp_broadcast_ip(ip_addr))
    tasks.append(async_send_ssdp_broadcast_ip(""))
    tasks.append(async_send_ssdp_broadcast_ip("0.0.0.0"))
    results = await asyncio.gather(*tasks)

    for result in results:
        _LOGGER.debug("SSDP broadcast result received: %s", result)
        urls = urls.union(result)

    _LOGGER.debug("Following devices found: %s", urls)
    return urls


async def async_send_ssdp_broadcast_ip(ip_addr: str) -> Set[str]:
    """Send SSDP broadcast messages to a single IP."""
    try:
        # Ignore 169.254.0.0/16 addresses
        if ip_addr.startswith("169.254."):
            return set()

        # Prepare socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.bind((ip_addr, 0))

        # Get asyncio loop
        loop = asyncio.get_event_loop()
        transport, protocol = await loop.create_datagram_endpoint(LGTVSSDP, sock=sock)

        # Wait for the timeout period
        await asyncio.sleep(SSDP_MX)

        # Close the connection
        transport.close()

        _LOGGER.debug("Got %s results after SSDP queries using ip %s", len(protocol.urls), ip_addr)

        return protocol.urls
    # pylint: disable = W0718
    except Exception:
        return set()


def evaluate_scpd_xml(url: str, response: Response) -> Optional[Dict]:
    """
    Evaluate SCPD XML.

    Returns dictionary with keys "host", "modelName", "friendlyName" and
    "presentationURL" if a Orange TV device was found and "None" if not.
    """
    # pylint: disable=W0718
    try:
        root = fromstring(response.text)
        # Look for manufacturer "SoftAtHome" in response.
        # Using "try" in case tags are not available in XML
        device = {}
        device_xml = None

        device["manufacturer"] = root.find(SCPD_DEVICE).find(SCPD_MANUFACTURER).text

        _LOGGER.debug("Device %s has manufacturer %s", url, device["manufacturer"])

        if not device["manufacturer"] in SUPPORTED_MANUFACTURERS:
            return None

        if root.find(SCPD_DEVICE).find(SCPD_DEVICETYPE).text in SUPPORTED_DEVICETYPES:
            device_xml = root.find(SCPD_DEVICE)
        elif root.find(SCPD_DEVICE).find(SCPD_DEVICELIST) is not None:
            for dev in root.find(SCPD_DEVICE).find(SCPD_DEVICELIST):
                if dev.find(SCPD_DEVICETYPE).text in SUPPORTED_DEVICETYPES and dev.find(SCPD_SERIALNUMBER) is not None:
                    device_xml = dev
                    break

        if device_xml is None:
            return None

        if device_xml.find(SCPD_PRESENTATIONURL) is not None:
            device["host"] = urlparse(device_xml.find(SCPD_PRESENTATIONURL).text).hostname
            device["presentationURL"] = device_xml.find(SCPD_PRESENTATIONURL).text
        else:
            device["host"] = urlparse(url).hostname

        device["modelName"] = device_xml.find(SCPD_MODELNAME).text
        device["serialNumber"] = device_xml.find(SCPD_SERIALNUMBER).text
        device["friendlyName"] = device_xml.find(SCPD_FRIENDLYNAME).text

        if device_xml.find(SCPD_WIREDMAC) is not None:
            device["wiredMac"] = device_xml.find(SCPD_WIREDMAC).text
        if device_xml.find(SCPD_WIFIMAC) is not None:
            device["wifiMac"] = device_xml.find(SCPD_WIFIMAC).text

        return device
    except Exception as err:
        _LOGGER.error("Error occurred during evaluation of SCPD XML from URI %s: %s", url, err)
        return None


class LGTVSSDP(asyncio.DatagramProtocol):
    """Implements datagram protocol for SSDP discovery of Orange TV devices."""

    def __init__(self) -> None:
        """Create instance."""
        self.urls = set()

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        """Send SSDP request when connection was made."""
        # Prepare SSDP and send broadcast message
        for ssdp_st in SSDP_ST_LIST:
            request = ssdp_request(ssdp_st)
            transport.sendto(request, SSDP_TARGET)
            _LOGGER.debug("SSDP request sent %s", request)

    def datagram_received(self, data: bytes, addr: Tuple[str, int]) -> None:
        """Receive responses to SSDP call."""
        # Some string operations to get the receivers URL
        # which could be found between LOCATION and end of line of the response
        _LOGGER.debug("Response to SSDP call received: %s", data)
        data_text = data.decode("utf-8")
        match = SSDP_LOCATION_PATTERN.search(data_text)
        if match:
            self.urls.add(match.group(0))
