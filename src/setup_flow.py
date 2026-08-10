"""
Setup flow for LG TV integration.

:copyright: (c) 2025 by Albaintor.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import asyncio
import copy
import ipaddress
import logging
import os
import socket
from enum import IntEnum
from typing import Any

from aiowebostv import WebOsClient
from ucapi import (
    AbortDriverSetup,
    DriverSetupRequest,
    IntegrationAPI,
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
from setup_fields import SETUP_DEVICE_FIELDS, SETUP_FIELDS, TEST_SETUP_FIELDS

_LOG = logging.getLogger(__name__)


# pylint: disable=W1405,C0103


class SetupSteps(IntEnum):
    """Enumeration of setup steps to keep track of user data responses."""

    INIT = 0
    WORKFLOW_MODE = 1
    DEVICE_CONFIGURATION_MODE = 2
    DISCOVER = 3
    DEVICE_CHOICE = 4
    ADDITIONAL_SETTINGS = 5
    TEST_WAKEONLAN = 6
    BACKUP_RESTORE = 7


def set_setup_field(fields: list[dict[str, Any]], field_id: str, value: Any):
    """Set field value from field id."""
    for field in fields:
        if field.get("id") == field_id and (field_entry := field.get("field")):
            if isinstance(field_entry, dict):
                for val in field_entry.values():
                    if isinstance(val, dict):
                        val["value"] = value


class SetupFlow:
    """Setup flow for LG TV integration."""

    def __init__(self, api: IntegrationAPI):
        self._api = api
        self._setup_step = SetupSteps.INIT
        self._cfg_add_device: bool = False
        self._discovered_devices: list[dict[str, Any]] = []
        self._configured_device_choices: dict[str, str] = {}
        self._pairing_lg_tv: WebOsClient | None = None
        self._reconfigured_device: LGConfigDevice | None = None
        self._user_input_discovery = RequestUserInput(
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
                    "label": {
                        "en": "IP address",
                        "de": "IP-Adresse",
                        "fr": "Adresse IP",
                    },
                },
            ],
        )

    @staticmethod
    def _config_store() -> config.Devices:
        """Return the initialized configuration store."""
        if config.devices is None:
            raise RuntimeError("Device configuration is not initialized")
        return config.devices

    def _current_device(self) -> LGConfigDevice:
        """Return the device selected by the active setup flow."""
        if self._reconfigured_device is None:
            raise RuntimeError("No device is selected for configuration")
        return self._reconfigured_device

    @staticmethod
    def _string_input(msg: UserDataResponse, key: str, default: str = "") -> str:
        """Read a string setup value, rejecting values of another type."""
        value = msg.input_values.get(key, default)
        return value if isinstance(value, str) else default

    # pylint: disable=R0911
    async def driver_setup_handler(self, msg: SetupDriver) -> SetupAction:
        """
        Dispatch driver setup requests to corresponding handlers.

        Either start the setup process or handle the selected LG TV device.

        :param msg: the setup driver request object, either DriverSetupRequest or UserDataResponse
        :return: the setup action on how to continue
        """
        if isinstance(msg, DriverSetupRequest):
            self._setup_step = SetupSteps.INIT
            self._cfg_add_device = False
            return await self.handle_driver_setup(msg)
        if isinstance(msg, UserDataResponse):
            _LOG.debug(
                "Setup handler message : step %s, message : %s", self._setup_step, msg
            )
            if self._setup_step == SetupSteps.WORKFLOW_MODE:
                if msg.input_values.get("configuration_mode", "") == "normal":
                    self._setup_step = SetupSteps.DEVICE_CONFIGURATION_MODE
                    _LOG.debug("Starting normal setup workflow")
                    return self._user_input_discovery
                _LOG.debug("User requested backup/restore of configuration")
                return await self._handle_backup_restore_step()
            if self._setup_step == SetupSteps.DEVICE_CONFIGURATION_MODE:
                if "action" in msg.input_values:
                    _LOG.debug("Setup flow starts with existing configuration")
                    return await self.handle_configuration_mode(msg)
                _LOG.debug("Setup flow configuration mode")
                return await self._handle_discovery(msg)
            # if self._setup_step == SetupSteps.DEVICE_CONFIGURATION_MODE and "action" in msg.input_values:
            #     return await handle_configuration_mode(msg)
            if (
                self._setup_step == SetupSteps.DISCOVER
                and "address" in msg.input_values
            ):
                return await self._handle_discovery(msg)
            if (
                self._setup_step == SetupSteps.DEVICE_CHOICE
                and "choice" in msg.input_values
            ):
                return await self.handle_device_choice(msg)
            if (
                self._setup_step == SetupSteps.ADDITIONAL_SETTINGS
                and "mac_address" in msg.input_values
            ):
                return await self.handle_additional_settings(msg)
            if (
                self._setup_step == SetupSteps.TEST_WAKEONLAN
                and "mac_address" in msg.input_values
            ):
                return await self.handle_wake_on_lan(msg)
            if self._setup_step == SetupSteps.BACKUP_RESTORE:
                return await self._handle_backup_restore(msg)
            _LOG.error("No or invalid user response was received: %s", msg)
        elif isinstance(msg, UserConfirmationResponse):
            if self._setup_step == SetupSteps.TEST_WAKEONLAN:
                if msg.confirm:
                    return self.get_wakeonlan_settings()
                if self._reconfigured_device is not None:
                    return self.get_additional_settings(self._reconfigured_device)
        elif isinstance(msg, AbortDriverSetup):
            _LOG.info("Setup was aborted with code: %s", msg.error)
            if self._pairing_lg_tv is not None:
                await self._pairing_lg_tv.disconnect()
            self._setup_step = SetupSteps.INIT

        # user confirmation not used in setup process
        # if isinstance(msg, UserConfirmationResponse):
        #     return handle_user_confirmation(msg)

        return SetupError()

    async def handle_driver_setup(
        self, msg: DriverSetupRequest
    ) -> RequestUserInput | SetupError:
        """
        Start driver setup.

        Initiated by Remote Two to set up the driver.
        Ask user to enter ip-address for manual configuration, otherwise auto-discovery is used.

        :param msg: not used, we don't have any input fields in the first setup screen.
        :return: the setup action on how to continue
        """
        # workaround for web-configurator not picking up first response
        await asyncio.sleep(1)

        reconfigure = msg.reconfigure
        _LOG.debug("Handle driver setup, reconfigure=%s", reconfigure)
        if reconfigure:
            self._setup_step = SetupSteps.DEVICE_CONFIGURATION_MODE

            # get all configured devices for the user to choose from
            dropdown_devices = []
            self._configured_device_choices = {}
            for index, device in enumerate(self._config_store().all()):
                choice_id = device.id or f"legacy-device-{index}"
                self._configured_device_choices[choice_id] = device.id
                identifier = device.id or device.address
                dropdown_devices.append(
                    {"id": choice_id, "label": {"en": f"{device.name} ({identifier})"}}
                )

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

            dropdown_actions.append(
                {
                    "id": "backup_restore",
                    "label": {
                        "en": "Backup or restore devices configuration",
                        "fr": "Sauvegarder ou restaurer la configuration des appareils",
                    },
                },
            )

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
        self._config_store().clear()  # triggers device instance removal
        self._setup_step = SetupSteps.WORKFLOW_MODE
        return RequestUserInput(
            {"en": "Configuration mode", "de": "Konfigurations-Modus"},
            [
                {
                    "field": {
                        "dropdown": {
                            "value": "normal",
                            "items": [
                                {
                                    "id": "normal",
                                    "label": {
                                        "en": "Start the configuration of the integration",
                                        "fr": "Démarrer la configuration de l'intégration",
                                    },
                                },
                                {
                                    "id": "backup_restore",
                                    "label": {
                                        "en": "Backup or restore devices configuration",
                                        "fr": "Sauvegarder ou restaurer la configuration des appareils",
                                    },
                                },
                            ],
                        }
                    },
                    "id": "configuration_mode",
                    "label": {
                        "en": "Configuration mode",
                        "fr": "Mode de configuration",
                    },
                }
            ],
        )

    async def handle_configuration_mode(
        self, msg: UserDataResponse
    ) -> RequestUserInput | SetupComplete | SetupError:
        """
        Process user data response in a setup process.

        If ``address`` field is set by the user: try connecting to device and retrieve model information.
        Otherwise, start Android TV discovery and present the found devices to the user to choose from.

        :param msg: response data from the requested user data
        :return: the setup action on how to continue
        """
        action = self._string_input(msg, "action")

        _LOG.debug("Handle configuration mode")

        # workaround for web-configurator not picking up first response
        await asyncio.sleep(1)

        match action:
            case "add":
                self._cfg_add_device = True
            case "remove":
                choice = self._string_input(msg, "choice")
                device_id = self._configured_device_choices.get(choice, choice)
                devices = self._config_store()
                if not devices.remove(device_id):
                    _LOG.warning(
                        "Could not remove device from configuration: %s", choice
                    )
                    return SetupError(error_type=IntegrationSetupError.OTHER)
                devices.store()
                return SetupComplete()
            case "configure":
                choice = self._string_input(msg, "choice")
                device_id = self._configured_device_choices.get(choice, choice)
                devices = self._config_store()
                if not devices.contains(device_id):
                    _LOG.warning(
                        "Could not configure existing device from configuration: %s",
                        choice,
                    )
                    return SetupError(error_type=IntegrationSetupError.OTHER)
                self._reconfigured_device = devices.get(device_id)
                if self._reconfigured_device is None:
                    return SetupError(error_type=IntegrationSetupError.OTHER)
                return self.get_additional_settings(self._reconfigured_device)
            case "reset":
                self._config_store().clear()  # triggers device instance removal
            case "backup_restore":
                return await self._handle_backup_restore_step()
            case _:
                _LOG.error("Invalid configuration action: %s", action)
                return SetupError(error_type=IntegrationSetupError.OTHER)

        self._setup_step = SetupSteps.DISCOVER
        return self._user_input_discovery

    async def _handle_discovery(
        self, msg: UserDataResponse
    ) -> RequestUserInput | SetupError:
        """
        Process user data response in a setup process.

        If ``address`` field is set by the user: try connecting to device and retrieve model information.
        Otherwise, start LG TV discovery and present the found devices to the user to choose from.

        :param msg: response data from the requested user data
        :return: the setup action on how to continue
        """
        # pylint: disable=W0718
        # clear all configured devices and any previous pairing attempt
        if self._pairing_lg_tv:
            await self._pairing_lg_tv.disconnect()
            self._pairing_lg_tv = None

        dropdown_items = []
        _LOG.debug("Handle driver setup with discovery")

        address = self._string_input(msg, "address")
        if address:
            _LOG.debug("Starting manual driver setup for %s", address)
            try:
                # simple connection check
                self._pairing_lg_tv = WebOsClient(address)
                await self._pairing_lg_tv.connect()
                try:
                    info = await self._pairing_lg_tv.get_system_info()
                    model_name = info.get("modelName")
                except Exception as exc:
                    _LOG.info(
                        "Cannot get system info, trying to retrieve the model name either way %s: %s",
                        address,
                        exc,
                    )
                    info = self._pairing_lg_tv.tv_info
                    model_name = info.system.get("modelName", "LG")
                    # unique_id = info.software.get("device_id")

                dropdown_items.append(
                    {"id": address, "label": {"en": f"{model_name} [{address}]"}}
                )
                await self._pairing_lg_tv.disconnect()
            except WEBOSTV_EXCEPTIONS as ex:
                _LOG.error(
                    "Cannot connect to manually entered address %s: %s", address, ex
                )
                return SetupError(error_type=IntegrationSetupError.CONNECTION_REFUSED)
        else:
            _LOG.debug("Starting auto-discovery driver setup")
            self._discovered_devices = await discover.async_identify_lg_devices()
            for device in self._discovered_devices:
                device_data = {
                    "id": device.get("host"),
                    "label": {
                        "en": f"{device.get('friendlyName')} [{device.get('host')}]"
                    },
                }
                dropdown_items.append(device_data)

        if not dropdown_items:
            _LOG.warning("No LG TVs found")
            return SetupError(error_type=IntegrationSetupError.NOT_FOUND)

        self._setup_step = SetupSteps.DEVICE_CHOICE
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

    async def handle_device_choice(
        self, msg: UserDataResponse
    ) -> RequestUserInput | SetupError:
        """
        Process user data response in a setup process.

        Driver setup callback to provide requested user data during the setup process.

        :param msg: response data from the requested user data
        :return: the setup action on how to continue: SetupComplete if a valid LG TV device was chosen.
        """
        discovered_device = None
        host = self._string_input(msg, "choice")
        if not host:
            return SetupError(error_type=IntegrationSetupError.NOT_FOUND)
        mac_address: str | None = None
        mac_address2: str | None = None
        model_name = "LG"
        serial_number: str | None = None
        software_device_id: str | None = None
        # pylint: disable=W0718

        if self._discovered_devices:
            for device in self._discovered_devices:
                if device.get("host", None) == host:
                    discovered_device = device
                    if isinstance(device.get("wiredMac"), str):
                        mac_address = device["wiredMac"]
                    if isinstance(device.get("wifiMac"), str):
                        mac_address2 = device["wifiMac"]

        _LOG.debug(
            "Chosen LG TV: %s (wired mac %s, wifi mac %s). Trying to connect and retrieve device information...",
            host,
            mac_address,
            mac_address2,
        )
        try:
            # simple connection check
            self._pairing_lg_tv = WebOsClient(host)
            await self._pairing_lg_tv.connect()
            key = self._pairing_lg_tv.client_key or ""
            try:
                info = await self._pairing_lg_tv.get_system_info()
                if isinstance(info.get("modelName"), str):
                    model_name = info["modelName"]
                if isinstance(info.get("serialNumber"), str):
                    serial_number = info["serialNumber"]
                info = await self._pairing_lg_tv.get_software_info()
                if isinstance(info.get("device_id"), str):
                    software_device_id = info["device_id"]
            except Exception as ex:
                _LOG.info(
                    "Cannot get system info, trying to retrieve the model name either way %s: %s",
                    host,
                    ex,
                )
                info = self._pairing_lg_tv.tv_info
                if isinstance(info.system.get("modelName"), str):
                    model_name = info.system["modelName"]
                if isinstance(info.system.get("serialNumber"), str):
                    serial_number = info.system["serialNumber"]
                if isinstance(info.software.get("device_id"), str):
                    software_device_id = info.software["device_id"]

            if discovered_device and isinstance(
                discovered_device.get("friendlyName"), str
            ):
                model_name = discovered_device["friendlyName"]

            if mac_address is None and software_device_id:
                mac_address = software_device_id
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.error("Cannot connect to %s: %s", host, ex)
            return SetupError(error_type=IntegrationSetupError.CONNECTION_REFUSED)

        unique_id = (
            software_device_id
            or serial_number
            or (discovered_device or {}).get("serialNumber")
            or mac_address
            or mac_address2
            or host
        )

        self._reconfigured_device = LGConfigDevice(
            id=unique_id,
            name=model_name,
            address=host,
            key=key,
            mac_address=mac_address,
            mac_address2=mac_address2,
            interface="0.0.0.0",
            broadcast=None,
            wol_port=9,
            update_apps_list=True,
            log=False,
        )

        return self.get_additional_settings(self._reconfigured_device)

    def get_additional_settings(
        self, config_device: LGConfigDevice
    ) -> RequestUserInput:
        """Extract additional settings for device registration."""
        self._setup_step = SetupSteps.ADDITIONAL_SETTINGS
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
            *copy.deepcopy(SETUP_DEVICE_FIELDS),
            *copy.deepcopy(SETUP_FIELDS),
        ]
        set_setup_field(additional_fields, "address", config_device.address)
        set_setup_field(additional_fields, "mac_address", config_device.mac_address)
        set_setup_field(additional_fields, "mac_address2", config_device.mac_address2)
        set_setup_field(additional_fields, "interface", config_device.interface)
        set_setup_field(additional_fields, "broadcast", config_device.broadcast)
        set_setup_field(additional_fields, "wol_port", config_device.wol_port)

        return RequestUserInput(
            title={
                "en": "Additional settings",
                "fr": "Paramètres supplémentaires",
            },
            settings=additional_fields,
        )

    async def _handle_backup_restore_step(self) -> RequestUserInput:
        self._setup_step = SetupSteps.BACKUP_RESTORE
        current_config = self._config_store().export()

        _LOG.debug("Handle backup/restore step")

        return RequestUserInput(
            {
                "en": "Backup or restore devices configuration (all existing devices will be removed)",
                "fr": "Sauvegarder ou restaurer la configuration des appareils (tous les appareils existants "
                "seront supprimés)",
            },
            [
                {
                    "field": {
                        "textarea": {
                            "value": current_config,
                        }
                    },
                    "id": "config",
                    "label": {
                        "en": "Devices configuration",
                        "fr": "Configuration des appareils",
                    },
                },
            ],
        )

    def _is_ipv6_address(self, ip_address: str) -> bool:
        """Check if this is an IPV6 address."""
        try:
            return isinstance(ipaddress.ip_address(ip_address), ipaddress.IPv6Address)
        except ValueError:
            return False

    def get_wakeonlan_settings(self) -> RequestUserInput:
        """Set settings for wake on lan."""
        # pylint: disable = W0718
        broadcast = ""
        interface: str | None = ""
        try:
            interface = os.getenv("UC_INTEGRATION_INTERFACE")
            if interface is None or interface == "127.0.0.1":
                interface = None
                ips = [
                    address
                    for info in socket.getaddrinfo(socket.gethostname(), None)
                    if isinstance(address := info[4][0], str)
                ]
                for ip_addr in ips:
                    if (
                        ip_addr is None
                        or ip_addr == "127.0.0.1"
                        or self._is_ipv6_address(ip_addr)
                    ):
                        continue
                    interface = ip_addr
                    break
            if interface is not None:
                broadcast = interface[: interface.rfind(".") + 1] + "255"
        except Exception:
            pass

        user_input = RequestUserInput(
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
                *copy.deepcopy(SETUP_FIELDS),
                *copy.deepcopy(TEST_SETUP_FIELDS),
            ],
        )
        device = self._current_device()
        set_setup_field(user_input.settings, "address", device.address)
        set_setup_field(user_input.settings, "mac_address", device.mac_address)
        set_setup_field(user_input.settings, "mac_address2", device.mac_address2)
        set_setup_field(user_input.settings, "interface", device.interface)
        set_setup_field(user_input.settings, "broadcast", device.broadcast)
        set_setup_field(user_input.settings, "wol_port", device.wol_port)
        set_setup_field(
            user_input.settings,
            "update_apps_list",
            device.update_apps_list,
        )
        set_setup_field(user_input.settings, "log", device.log)

        return user_input

    async def handle_additional_settings(
        self, msg: UserDataResponse
    ) -> RequestUserConfirmation | SetupComplete | SetupError:
        """Handle setup flow for additional settings."""
        device = self._current_device()
        address = self._string_input(msg, "address")
        mac_address: str | None = self._string_input(msg, "mac_address")
        mac_address2: str | None = self._string_input(msg, "mac_address2")
        interface: str | None = self._string_input(msg, "interface")
        broadcast: str | None = self._string_input(msg, "broadcast")
        test_wakeonlan = msg.input_values.get("test_wakeonlan", "false") == "true"
        pairing = msg.input_values.get("pairing", "false") == "true"
        update_apps_list = msg.input_values.get("update_apps_list", "false") == "true"
        log = msg.input_values.get("log", "false") == "true"
        _LOG.debug("Handle additional settings")

        try:
            wolport = int(msg.input_values.get("wolport", 9))
        except (TypeError, ValueError):
            return SetupError(error_type=IntegrationSetupError.OTHER)

        if address != "":
            device.address = address
        if mac_address == "":
            mac_address = None
        if mac_address2 == "":
            mac_address2 = None
        if broadcast == "":
            broadcast = None
        if interface == "":
            interface = None

        device.mac_address = mac_address
        device.mac_address2 = mac_address2
        device.interface = interface
        device.broadcast = broadcast
        device.wol_port = wolport
        device.log = log
        device.update_apps_list = update_apps_list

        if pairing:
            client = WebOsClient(device.address)
            await client.connect()
            if client.client_key is not None:
                device.key = client.client_key
            await client.disconnect()

        _LOG.info("[Additional settings] Setup updated settings %s", device)
        self._config_store().add_or_update(device, test_wakeonlan is False)

        if self._pairing_lg_tv:
            await self._pairing_lg_tv.disconnect()
            self._pairing_lg_tv = None

        if test_wakeonlan:
            _LOG.debug("Testing Wake On Lan")
            self._setup_step = SetupSteps.TEST_WAKEONLAN
            return await self.handle_wake_on_lan(msg)

        # LG TV device connection will be triggered with subscribe_entities request
        await asyncio.sleep(1)
        _LOG.info(
            "Setup successfully completed for %s (%s)",
            device.name,
            device.id,
        )
        return SetupComplete()

    async def handle_wake_on_lan(
        self, msg: UserDataResponse
    ) -> RequestUserConfirmation | SetupError:
        """Handle wake on lan test."""
        configured_device = self._current_device()
        mac_address: str | None = self._string_input(msg, "mac_address")
        mac_address2: str | None = self._string_input(msg, "mac_address2")
        interface: str | None = self._string_input(msg, "interface")
        broadcast: str | None = self._string_input(msg, "broadcast")
        # test_wakeonlan = msg.input_values.get("test_wakeonlan", False)
        _LOG.debug("Handle wake on lan")
        wolport = 9
        try:
            wolport = int(msg.input_values.get("wolport", wolport))
        except (TypeError, ValueError):
            return SetupError(error_type=IntegrationSetupError.OTHER)

        if mac_address == "":
            mac_address = None
        if mac_address2 == "":
            mac_address2 = None
        if broadcast == "":
            broadcast = None
        if interface == "":
            interface = None

        configured_device.mac_address = mac_address
        configured_device.mac_address2 = mac_address2
        configured_device.interface = interface
        configured_device.broadcast = broadcast
        configured_device.wol_port = wolport

        _LOG.info("[Wake on lan] Setup updated settings %s", configured_device)
        devices = self._config_store()
        devices.add_or_update(configured_device, False)
        # triggers LG TV instance creation
        devices.store()

        requests = 0
        if configured_device.mac_address:
            requests += 1
        if configured_device.mac_address2:
            requests += 1

        device = LGDevice(device_config=configured_device)
        try:
            device.wakeonlan()
        except Exception as ex:
            _LOG.exception("Error during wake on lan %s", ex)
            raise ex

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

    async def _handle_backup_restore(
        self, msg: UserDataResponse
    ) -> SetupComplete | SetupError:
        """
        Process import of configuration

        :param msg: response data from the requested user data
        :return: the setup action on how to continue: SetupComplete after updating configuration
        """
        # flake8: noqa:F824
        # pylint: disable=W0602
        _LOG.debug("Handle backup/restore")
        updated_config = self._string_input(msg, "config")
        _LOG.info("Replacing configuration with : %s", updated_config)
        if not self._config_store().import_config(updated_config):
            _LOG.error(
                "Setup error : unable to import updated configuration %s",
                updated_config,
            )
            return SetupError(error_type=IntegrationSetupError.OTHER)
        _LOG.debug("Configuration imported successfully")

        await asyncio.sleep(1)
        return SetupComplete()
