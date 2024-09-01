"""
Setup flow for LG TV integration.

:copyright: (c) 2023 by Unfolded Circle ApS.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import asyncio
import logging
from enum import IntEnum

from getmac import getmac

import config
import discover
from aiowebostv import WebOsClient
from config import LGConfigDevice
from const import WEBOSTV_EXCEPTIONS
from ucapi import (
    AbortDriverSetup,
    DriverSetupRequest,
    IntegrationSetupError,
    RequestUserInput,
    SetupAction,
    SetupComplete,
    SetupDriver,
    SetupError,
    UserDataResponse,
)

_LOG = logging.getLogger(__name__)


# pylint: disable = W1405


class SetupSteps(IntEnum):
    """Enumeration of setup steps to keep track of user data responses."""

    INIT = 0
    CONFIGURATION_MODE = 1
    DISCOVER = 2
    DEVICE_CHOICE = 3
    ADDITIONAL_SETTINGS = 4


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


async def driver_setup_handler(msg: SetupDriver) -> SetupAction:
    """
    Dispatch driver setup requests to corresponding handlers.

    Either start the setup process or handle the selected LG TV device.

    :param msg: the setup driver request object, either DriverSetupRequest or UserDataResponse
    :return: the setup action on how to continue
    """
    global _setup_step
    global _cfg_add_device

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
        _LOG.error("No or invalid user response was received: %s", msg)
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
            info = await device.get_system_info()
            model_name = info.get("modelName")
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
                            "fr": "Après avoir cliqué sur suivant, un message de confirmation d'apparairage peut s'afficher sur la TV",
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
            }
        ],
    )

async def handle_device_choice(msg: UserDataResponse) -> RequestUserInput | SetupError:
    """
    Process user data response in a setup process.

    Driver setup callback to provide requested user data during the setup process.

    :param msg: response data from the requested user data
    :return: the setup action on how to continue: SetupComplete if a valid LG TV device was chosen.
    """
    global _discovered_devices
    global _pairing_lg_tv
    global _config_device
    global _setup_step
    discovered_device = None
    host = msg.input_values["choice"]

    if _discovered_devices:
        for device in _discovered_devices:
            if device.get("host", None) == host:
                discovered_device = device
                break

    _LOG.debug("Chosen LG TV: %s. Trying to connect and retrieve device information...", host)
    try:
        # simple connection check
        _pairing_lg_tv = WebOsClient(host)
        await _pairing_lg_tv.connect()
        key = _pairing_lg_tv.client_key
        info = await _pairing_lg_tv.get_system_info()
        model_name = info.get("modelName")
        if discovered_device and discovered_device.get("friendlyName"):
            model_name = discovered_device.get("friendlyName")
        # serial_number = info.get("serialNumber")
        info = await _pairing_lg_tv.get_software_info()
        mac_address = info.get("device_id")
    except WEBOSTV_EXCEPTIONS as ex:
        _LOG.error("Cannot connect to %s: %s", host, ex)
        return SetupError(error_type=IntegrationSetupError.CONNECTION_REFUSED)

    mac_address2 = None
    try:
        mac_address2 = getmac.get_mac_address(host)
        if mac_address2 == mac_address or mac_address2 == "ff:ff:ff:ff:ff:ff":
            mac_address2 = None
    except Exception:
        pass

    unique_id = mac_address
    _config_device = LGConfigDevice(id=unique_id, name=model_name, address=host, key=key,
                                    mac_address=mac_address, mac_address2=mac_address2)

    return get_additional_settings(_config_device)


def get_additional_settings(config_device: LGConfigDevice) -> RequestUserInput:
    global _setup_step
    _setup_step = SetupSteps.ADDITIONAL_SETTINGS
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
            "field": {"text": {"value": config_device.mac_address}},
            "id": "mac_address",
            "label": {"en": "Mac address", "de": "Mac address", "fr": "Adresse Mac"},
        }
    ]
    if config_device.mac_address2:
        additional_fields.append(
            {
                "field": {"text": {"value": config_device.mac_address2}},
                "id": "mac_address2",
                "label": {"en": "Second mac address", "fr": "Seconde adresse Mac"},
            }
        )
    return RequestUserInput(
        title={
            "en": "Additional settings",
            "fr": "Paramètres supplémentaires",
        },
        settings=additional_fields
    )


async def handle_additional_settings(msg: UserDataResponse) -> SetupComplete | SetupError:

    global _config_device
    global _pairing_lg_tv
    mac_address = msg.input_values.get("mac_address", "")
    mac_address2 = msg.input_values.get("mac_address2", None)
    if mac_address2 == "":
        mac_address2 = None

    _config_device.mac_address = mac_address
    _config_device.mac_address2 = mac_address2

    config.devices.add_or_update(_config_device)
    # triggers LG TV instance creation
    config.devices.store()

    if _pairing_lg_tv:
        await _pairing_lg_tv.disconnect()
        _pairing_lg_tv = None

    # LG TV device connection will be triggered with subscribe_entities request
    await asyncio.sleep(1)
    _LOG.info("Setup successfully completed for %s (%s)", _config_device.name, _config_device.id)
    return SetupComplete()
