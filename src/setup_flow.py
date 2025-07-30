"""
Setup flow for LG TV integration.

:copyright: (c) 2023 by Unfolded Circle ApS.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import asyncio
import ipaddress
import logging
import os
import socket
from enum import IntEnum

from aiowebostv import WebOsClient
from ucapi import (
    AbortDriverSetup,
    DriverSetupRequest,
    IntegrationSetupError,
    RequestUserConfirmation,
    RequestUserInput,
    SetupAction,
    SetupComplete,
    SetupDriver,
    SetupError,
    UserConfirmationResponse,
    UserDataResponse,
)

import config
import discover
from config import LGConfigDevice
from const import WEBOSTV_EXCEPTIONS
from lg import LGDevice

_LOG = logging.getLogger(__name__)


# pylint: disable = W1405


class SetupSteps(IntEnum):
    """Enumeration of setup steps to keep track of user data responses."""

    INIT = 0
    CONFIGURATION_MODE = 1
    DISCOVER = 2
    DEVICE_CHOICE = 3
    ADDITIONAL_SETTINGS = 4
    TEST_WAKEONLAN = 5


_setup_step = SetupSteps.INIT
_cfg_add_device: bool = False
_discovered_devices: list[dict[str, str]] = []
_pairing_lg_tv: WebOsClient | None = None
_config_device: LGConfigDevice | None = None
_user_input_discovery = RequestUserInput(
    {"en": "Setup mode", "de": "Setup Modus"},
    [
        {
            "id": "info",
            "label": {
                "en": "Discover or connect to LG TV devices",
                "de": "Suche oder Verbinde auf LG TV Gerät",
                "fr": "Découverte ou connexion à votre TV LG",
            },
            "field": {
                "label": {
                    "value": {
                        "en": "Leave blank to use auto-discovery.",
                        "de": "Leer lassen, um automatische Erkennung zu verwenden.",
                        "fr": "Laissez le champ vide pour utiliser la découverte automatique.",
                    }
                }
            },
        },
        {
            "field": {"text": {"value": ""}},
            "id": "address",
            "label": {"en": "IP address", "de": "IP-Adresse", "fr": "Adresse IP"},
        },
    ],
)


# pylint: disable=R0911
async def driver_setup_handler(msg: SetupDriver) -> SetupAction:
    """
    Dispatch driver setup requests to corresponding handlers.

    Either start the setup process or handle the selected LG TV device.

    :param msg: the setup driver request object, either DriverSetupRequest or UserDataResponse
    :return: the setup action on how to continue
    """
    global _setup_step
    global _cfg_add_device

    _LOG.debug("driver_setup_handler")

    if isinstance(msg, DriverSetupRequest):
        _setup_step = SetupSteps.INIT
        _cfg_add_device = False
        return await handle_driver_setup(msg)
    if isinstance(msg, UserDataResponse):
        _LOG.debug(msg)
        if _setup_step == SetupSteps.CONFIGURATION_MODE and "action" in msg.input_values:
            return await handle_configuration_mode(msg)
        if _setup_step == SetupSteps.DISCOVER and "address" in msg.input_values:
            return await _handle_discovery(msg)
        if _setup_step == SetupSteps.DEVICE_CHOICE and "choice" in msg.input_values:
            return await handle_device_choice(msg)
        if _setup_step == SetupSteps.ADDITIONAL_SETTINGS and "mac_address" in msg.input_values:
            return await handle_additional_settings(msg)
        if _setup_step == SetupSteps.TEST_WAKEONLAN and "mac_address" in msg.input_values:
            return await handle_wake_on_lan(msg)
        _LOG.error("No or invalid user response was received: %s", msg)
    elif isinstance(msg, UserConfirmationResponse):
        if _setup_step == SetupSteps.TEST_WAKEONLAN:
            if msg.confirm:
                return get_wakeonlan_settings()
            return get_additional_settings(_config_device)

    elif isinstance(msg, AbortDriverSetup):
        _LOG.info("Setup was aborted with code: %s", msg.error)
        if _pairing_lg_tv is not None:
            await _pairing_lg_tv.disconnect()
        _setup_step = SetupSteps.INIT

    # user confirmation not used in setup process
    # if isinstance(msg, UserConfirmationResponse):
    #     return handle_user_confirmation(msg)

    return SetupError()


async def handle_driver_setup(msg: DriverSetupRequest) -> RequestUserInput | SetupError:
    """
    Start driver setup.

    Initiated by Remote Two to set up the driver.
    Ask user to enter ip-address for manual configuration, otherwise auto-discovery is used.

    :param msg: not used, we don't have any input fields in the first setup screen.
    :return: the setup action on how to continue
    """
    global _setup_step

    # workaround for web-configurator not picking up first response
    await asyncio.sleep(1)

    reconfigure = msg.reconfigure
    _LOG.debug("Starting driver setup, reconfigure=%s", reconfigure)
    if reconfigure:
        _setup_step = SetupSteps.CONFIGURATION_MODE

        # get all configured devices for the user to choose from
        dropdown_devices = []
        for device in config.devices.all():
            dropdown_devices.append({"id": device.id, "label": {"en": f"{device.name} ({device.id})"}})

        # TODO #12 externalize language texts
        # build user actions, based on available devices
        dropdown_actions = [
            {
                "id": "add",
                "label": {
                    "en": "Add a new device",
                    "de": "Neues Gerät hinzufügen",
                    "fr": "Ajouter un nouvel appareil",
                },
            },
        ]

        # add remove & reset actions if there's at least one configured device
        if dropdown_devices:
            dropdown_actions.append(
                {
                    "id": "configure",
                    "label": {
                        "en": "Configure selected device",
                        "fr": "Configurer l'appareil sélectionné",
                    },
                },
            )
            dropdown_actions.append(
                {
                    "id": "remove",
                    "label": {
                        "en": "Delete selected device",
                        "de": "Selektiertes Gerät löschen",
                        "fr": "Supprimer l'appareil sélectionné",
                    },
                },
            )
            dropdown_actions.append(
                {
                    "id": "reset",
                    "label": {
                        "en": "Reset configuration and reconfigure",
                        "de": "Konfiguration zurücksetzen und neu konfigurieren",
                        "fr": "Réinitialiser la configuration et reconfigurer",
                    },
                },
            )
        else:
            # dummy entry if no devices are available
            dropdown_devices.append({"id": "", "label": {"en": "---"}})

        return RequestUserInput(
            {"en": "Configuration mode", "de": "Konfigurations-Modus"},
            [
                {
                    "field": {
                        "dropdown": {
                            "value": dropdown_devices[0]["id"],
                            "items": dropdown_devices,
                        }
                    },
                    "id": "choice",
                    "label": {
                        "en": "Configured devices",
                        "de": "Konfigurierte Geräte",
                        "fr": "Appareils configurés",
                    },
                },
                {
                    "field": {
                        "dropdown": {
                            "value": dropdown_actions[0]["id"],
                            "items": dropdown_actions,
                        }
                    },
                    "id": "action",
                    "label": {
                        "en": "Action",
                        "de": "Aktion",
                        "fr": "Appareils configurés",
                    },
                },
            ],
        )

    # Initial setup, make sure we have a clean configuration
    config.devices.clear()  # triggers device instance removal
    _setup_step = SetupSteps.DISCOVER
    return _user_input_discovery


async def handle_configuration_mode(msg: UserDataResponse) -> RequestUserInput | SetupComplete | SetupError:
    """
    Process user data response in a setup process.

    If ``address`` field is set by the user: try connecting to device and retrieve model information.
    Otherwise, start Android TV discovery and present the found devices to the user to choose from.

    :param msg: response data from the requested user data
    :return: the setup action on how to continue
    """
    global _setup_step
    global _cfg_add_device
    global _config_device

    action = msg.input_values["action"]

    # workaround for web-configurator not picking up first response
    await asyncio.sleep(1)

    match action:
        case "add":
            _cfg_add_device = True
        case "remove":
            choice = msg.input_values["choice"]
            if not config.devices.remove(choice):
                _LOG.warning("Could not remove device from configuration: %s", choice)
                return SetupError(error_type=IntegrationSetupError.OTHER)
            config.devices.store()
            return SetupComplete()
        case "configure":
            choice = msg.input_values["choice"]
            if not config.devices.contains(choice):
                _LOG.warning("Could not configure existing device from configuration: %s", choice)
                return SetupError(error_type=IntegrationSetupError.OTHER)
            _config_device = config.devices.get(choice)
            return get_additional_settings(_config_device)
        case "reset":
            config.devices.clear()  # triggers device instance removal
        case _:
            _LOG.error("Invalid configuration action: %s", action)
            return SetupError(error_type=IntegrationSetupError.OTHER)

    _setup_step = SetupSteps.DISCOVER
    return _user_input_discovery


async def _handle_discovery(msg: UserDataResponse) -> RequestUserInput | SetupError:
    """
    Process user data response in a setup process.

    If ``address`` field is set by the user: try connecting to device and retrieve model information.
    Otherwise, start LG TV discovery and present the found devices to the user to choose from.

    :param msg: response data from the requested user data
    :return: the setup action on how to continue
    """
    global _pairing_lg_tv
    global _setup_step
    global _discovered_devices

    # clear all configured devices and any previous pairing attempt
    if _pairing_lg_tv:
        await _pairing_lg_tv.disconnect()
        _pairing_lg_tv = None

    dropdown_items = []
    address = msg.input_values["address"]

    if address:
        _LOG.debug("Starting manual driver setup for %s", address)
        try:
            # simple connection check
            device = WebOsClient(address)
            await device.connect()
            try:
                info = await device.get_system_info()
                model_name = info.get("modelName")
            except Exception as exc:
                _LOG.info("Cannot get system info, trying to retrieve the model name either way %s: %s", address, exc)
                info = _pairing_lg_tv.tv_info
                model_name = info.system.get("modelName", "LG")
                # unique_id = info.software.get("device_id")

            dropdown_items.append({"id": address, "label": {"en": f"{model_name} [{address}]"}})
            await device.disconnect()
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.error("Cannot connect to manually entered address %s: %s", address, ex)
            return SetupError(error_type=IntegrationSetupError.CONNECTION_REFUSED)
    else:
        _LOG.debug("Starting auto-discovery driver setup")
        _discovered_devices = await discover.async_identify_lg_devices()
        for device in _discovered_devices:
            device_data = {
                "id": device.get("host"),
                "label": {"en": f"{device.get('friendlyName')} [{device.get('host')}]"},
            }
            dropdown_items.append(device_data)

    if not dropdown_items:
        _LOG.warning("No LG TVs found")
        return SetupError(error_type=IntegrationSetupError.NOT_FOUND)

    _setup_step = SetupSteps.DEVICE_CHOICE
    return RequestUserInput(
        {
            "en": "Please choose your LG TV",
            "de": "Bitte LG TV auswählen",
            "fr": "Sélectionnez votre TV LG",
        },
        [
            {
                "id": "info",
                "label": {
                    "en": "Please choose your LG TV",
                    "fr": "Sélectionnez votre TV LG",
                },
                "field": {
                    "label": {
                        "value": {
                            "en": "After clicking next you may be prompted to confirm pairing on your TV",
                            "fr": "Après avoir cliqué sur suivant, un message de confirmation d'apparairage peut "
                            "s'afficher sur la TV",
                        }
                    }
                },
            },
            {
                "field": {
                    "dropdown": {
                        "value": dropdown_items[0]["id"],
                        "items": dropdown_items,
                    }
                },
                "id": "choice",
                "label": {
                    "en": "Choose your LG TV",
                    "de": "Wähle deinen LG TV",
                    "fr": "Choisissez votre LG TV",
                },
            },
        ],
    )


async def handle_device_choice(msg: UserDataResponse) -> RequestUserInput | SetupError:
    """
    Process user data response in a setup process.

    Driver setup callback to provide requested user data during the setup process.

    :param msg: response data from the requested user data
    :return: the setup action on how to continue: SetupComplete if a valid LG TV device was chosen.
    """
    global _pairing_lg_tv
    global _config_device
    discovered_device = None
    host = msg.input_values["choice"]
    mac_address = None
    mac_address2 = None

    if _discovered_devices:
        for device in _discovered_devices:
            if device.get("host", None) == host:
                discovered_device = device
                if device.get("wiredMac"):
                    mac_address = device.get("wiredMac")
                if device.get("wifiMac"):
                    mac_address2 = device.get("wifiMac")

    _LOG.debug(
        "Chosen LG TV: %s (wired mac %s, wifi mac %s). Trying to connect and retrieve device information...",
        host,
        mac_address,
        mac_address2,
    )
    try:
        # simple connection check
        _pairing_lg_tv = WebOsClient(host)
        await _pairing_lg_tv.connect()
        key = _pairing_lg_tv.client_key
        try:
            info = await _pairing_lg_tv.get_system_info()
            model_name = info.get("modelName")
            # serial_number = info.get("serialNumber")
            info = await _pairing_lg_tv.get_software_info()
            unique_id = info.get("device_id")
        except Exception as ex:
            _LOG.info("Cannot get system info, trying to retrieve the model name either way %s: %s", host, ex)
            info = _pairing_lg_tv.tv_info
            model_name = info.system.get("modelName", "LG")
            unique_id = info.software.get("device_id")

        if discovered_device and discovered_device.get("friendlyName"):
            model_name = discovered_device.get("friendlyName")

        if mac_address is None:
            mac_address = unique_id
    except WEBOSTV_EXCEPTIONS as ex:
        _LOG.error("Cannot connect to %s: %s", host, ex)
        return SetupError(error_type=IntegrationSetupError.CONNECTION_REFUSED)

    _config_device = LGConfigDevice(
        id=unique_id,
        name=model_name,
        address=host,
        key=key,
        mac_address=mac_address,
        mac_address2=mac_address2,
        interface="0.0.0.0",
        broadcast=None,
        wol_port=9,
    )

    return get_additional_settings(_config_device)


def get_additional_settings(config_device: LGConfigDevice) -> RequestUserInput:
    """Extract additional settings for device registration."""
    global _setup_step
    _setup_step = SetupSteps.ADDITIONAL_SETTINGS
    if config_device.mac_address2 is None:
        config_device.mac_address2 = ""
    _LOG.debug("get_additional_settings")

    additional_fields = [
        {
            "id": "info",
            "label": {
                "en": "Additional settings",
                "fr": "Paramètres supplémentaires",
            },
            "field": {
                "label": {
                    "value": {
                        "en": "Mac address is necessary to turn on the TV, check the displayed value",
                        "fr": "L'adresse mac est nécessaire pour allumer la TV, vérifiez la valeur affichée",
                    }
                }
            },
        },
        {
            "field": {"text": {"value": config_device.address}},
            "id": "address",
            "label": {"en": "IP address", "fr": "Adresse IP"},
        },
        {
            "field": {"text": {"value": config_device.mac_address}},
            "id": "mac_address",
            "label": {"en": "Mac address (wired)", "fr": "Adresse Mac (cablé)"},
        },
        {
            "field": {"text": {"value": config_device.mac_address2}},
            "id": "mac_address2",
            "label": {"en": "Mac address (wifi)", "fr": "Adresse Mac (wifi)"},
        },
        {
            "field": {"text": {"value": config_device.interface}},
            "id": "interface",
            "label": {"en": "Interface to use for magic packet", "fr": 'Interface à utiliser pour le "magic packet"'},
        },
        {
            "field": {"text": {"value": config_device.broadcast}},
            "id": "broadcast",
            "label": {
                "en": "Broadcast address to use for magic packet (blank by default)",
                "fr": "Plage d'adresse à utiliser pour le magic packet (vide par défaut)",
            },
        },
        {
            "id": "wolport",
            "label": {
                "en": "Wake on lan port",
                "fr": "Numéro de port pour wake on lan",
            },
            "field": {"number": {"value": config_device.wol_port, "min": 1, "max": 65535, "steps": 1, "decimals": 0}},
        },
        {
            "id": "test_wakeonlan",
            "label": {
                "en": "Test turn on your configured TV (through wake on lan, TV should be off since 15 minutes at "
                "least)",
                "fr": "Tester la mise en marche de votre TV (via wake on lan, votre TV doit être éteinte depuis au "
                "moins 15 minutes)",
            },
            "field": {"checkbox": {"value": False}},
        },
        {
            "id": "pairing",
            "label": {
                "en": "Regenerate the pairing key and test connection",
                "fr": "Régénérer la clé d'appairage et tester la connection",
            },
            "field": {"checkbox": {"value": False}},
        },
    ]

    return RequestUserInput(
        title={
            "en": "Additional settings",
            "fr": "Paramètres supplémentaires",
        },
        settings=additional_fields,
    )


def _is_ipv6_address(ip_address: str) -> bool:
    """Check if this is an IPV6 address."""
    try:
        return isinstance(ipaddress.ip_address(ip_address), ipaddress.IPv6Address)
    except ValueError:
        return False


def get_wakeonlan_settings() -> RequestUserInput:
    """Set settings for wake on lan."""
    # pylint: disable = W0718
    broadcast = ""
    interface = ""
    try:
        interface = os.getenv("UC_INTEGRATION_INTERFACE")
        if interface is None or interface == "127.0.0.1":
            interface = None
            ips = [i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None)]
            for ip_addr in ips:
                if ip_addr is None or ip_addr == "127.0.0.1" or _is_ipv6_address(ip_addr):
                    continue
                interface = ip_addr
                break
        if interface is not None:
            broadcast = interface[: interface.rfind(".") + 1] + "255"
    except Exception:
        pass

    return RequestUserInput(
        title={
            "en": "Test switching on your LG TV",
            "fr": "Test de mise en marche de votre TV LG",
        },
        settings=[
            {
                "id": "info",
                "label": {
                    "en": "Test switching on your LG TV",
                    "fr": "Test de mise en marche de votre TV LG",
                },
                "field": {
                    "label": {
                        "value": {
                            "en": f"Remote interface {interface} : suggested broadcast {broadcast}",
                            "fr": f"Adresse de la télécommande {interface} : broadcast suggéré {broadcast}",
                        }
                    }
                },
            },
            {
                "field": {"text": {"value": _config_device.mac_address}},
                "id": "mac_address",
                "label": {"en": "First mac address", "fr": "Première adresse Mac"},
            },
            {
                "field": {"text": {"value": _config_device.mac_address2}},
                "id": "mac_address2",
                "label": {"en": "Second mac address", "fr": "Deuxième adresse Mac"},
            },
            {
                "field": {"text": {"value": _config_device.interface}},
                "id": "interface",
                "label": {"en": "Interface (optional)", "fr": "Interface (optionnel)"},
            },
            {
                "field": {"text": {"value": _config_device.broadcast}},
                "id": "broadcast",
                "label": {"en": "Broadcast (optional)", "fr": "Broadcast (optionnel)"},
            },
            {
                "id": "wolport",
                "label": {
                    "en": "Wake on lan port",
                    "fr": "Numéro de port pour wake on lan",
                },
                "field": {
                    "number": {"value": _config_device.wol_port, "min": 1, "max": 65535, "steps": 1, "decimals": 0}
                },
            },
        ],
    )


async def handle_additional_settings(msg: UserDataResponse) -> RequestUserConfirmation | SetupComplete | SetupError:
    """Handle setup flow for additional settings."""
    global _pairing_lg_tv
    global _setup_step
    address = msg.input_values.get("address", "")
    mac_address = msg.input_values.get("mac_address", "")
    mac_address2 = msg.input_values.get("mac_address2", "")
    interface = msg.input_values.get("interface", "")
    broadcast = msg.input_values.get("broadcast", "")
    test_wakeonlan = msg.input_values.get("test_wakeonlan", "false") == "true"
    pairing = msg.input_values.get("pairing", "false") == "true"
    try:
        wolport = int(msg.input_values.get("wolport", 9))
    except ValueError:
        return SetupError(error_type=IntegrationSetupError.OTHER)

    if address != "":
        _config_device.address = address
    if mac_address == "":
        mac_address = None
    if mac_address2 == "":
        mac_address2 = None
    if broadcast == "":
        broadcast = None
    if interface == "":
        interface = None

    _config_device.mac_address = mac_address
    _config_device.mac_address2 = mac_address2
    _config_device.interface = interface
    _config_device.broadcast = broadcast
    _config_device.wol_port = wolport

    if pairing:
        client = WebOsClient(_config_device.address)
        await client.connect()
        _config_device.key = client.client_key
        await client.disconnect()

    _LOG.info("Setup updated settings %s", _config_device)
    config.devices.add_or_update(_config_device)
    # triggers LG TV instance creation

    if _pairing_lg_tv:
        await _pairing_lg_tv.disconnect()
        _pairing_lg_tv = None

    if test_wakeonlan:
        _setup_step = SetupSteps.TEST_WAKEONLAN
        return await handle_wake_on_lan(msg)

    # LG TV device connection will be triggered with subscribe_entities request
    await asyncio.sleep(1)
    _LOG.info("Setup successfully completed for %s (%s)", _config_device.name, _config_device.id)
    return SetupComplete()


async def handle_wake_on_lan(msg: UserDataResponse) -> RequestUserConfirmation | SetupError:
    """Handle wake on lan test."""
    mac_address = msg.input_values.get("mac_address", "")
    mac_address2 = msg.input_values.get("mac_address2", "")
    interface = msg.input_values.get("interface", "")
    broadcast = msg.input_values.get("broadcast", "")
    # test_wakeonlan = msg.input_values.get("test_wakeonlan", False)
    wolport = 9
    try:
        wolport = int(msg.input_values.get("wolport", wolport))
    except ValueError:
        return SetupError(error_type=IntegrationSetupError.OTHER)

    if mac_address == "":
        mac_address = None
    if mac_address2 == "":
        mac_address2 = None
    if broadcast == "":
        broadcast = None
    if interface == "":
        interface = None

    _config_device.mac_address = mac_address
    _config_device.mac_address2 = mac_address2
    _config_device.interface = interface
    _config_device.broadcast = broadcast
    _config_device.wol_port = wolport

    _LOG.info("Setup updated settings %s", _config_device)
    config.devices.add_or_update(_config_device)
    # triggers LG TV instance creation
    config.devices.store()

    requests = 0
    if _config_device.mac_address:
        requests += 1
    if _config_device.mac_address2:
        requests += 1

    device = LGDevice(device_config=_config_device)
    device.wakeonlan()

    return RequestUserConfirmation(
        title={
            "en": f"{requests} requests sent to the TV",
            "fr": f"{requests} requêtes envoyées au téléviseur",
        },
        header={
            "en": "Do you want to try another configuration ?",
            "fr": "Voulez-vous essayer une autre configuration ?",
        },
    )
