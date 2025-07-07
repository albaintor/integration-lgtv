#!/usr/bin/env python3
"""
This module implements a Remote Two integration driver for LG TV receivers.

:copyright: (c) 2023 by Unfolded Circle ApS.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import asyncio
import logging
import os
import sys
from typing import Any

import ucapi
from ucapi.media_player import Attributes as MediaAttr
from ucapi.media_player import States

import config
import lg
import media_player
import remote
import setup_flow
from config import device_from_entity_id
from const import WEBOSTV_EXCEPTIONS

_LOG = logging.getLogger("driver")  # avoid having __main__ in log messages
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)

# Global variables
api = ucapi.IntegrationAPI(_LOOP)
# Map of id -> LG instance
_configured_devices: dict[str, lg.LGDevice] = {}


@api.listens_to(ucapi.Events.CONNECT)
async def on_r2_connect_cmd() -> None:
    """Connect all configured TVs when the Remote Two sends the connect command."""
    # TODO check if we were in standby and ignore the call? We'll also get an EXIT_STANDBY
    _LOG.debug("R2 connect command: connecting device(s)")
    for device in _configured_devices.values():
        # start background task
        # TODO ? what is the connect event for (against exit from standby)
        # await _LOOP.create_task(device.power_on())
        try:
            _LOOP.create_task(device.connect())
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.debug(
                "Could not connect to device, probably because it is starting with magic packet %s",
                ex,
            )
    await api.set_device_state(ucapi.DeviceStates.CONNECTED)


@api.listens_to(ucapi.Events.DISCONNECT)
async def on_r2_disconnect_cmd():
    """Disconnect all configured TVs when the Remote Two sends the disconnect command."""
    for device in _configured_devices.values():
        # start background task
        await _LOOP.create_task(device.disconnect())


@api.listens_to(ucapi.Events.ENTER_STANDBY)
async def on_r2_enter_standby() -> None:
    """
    Enter standby notification from Remote Two.

    Disconnect every LG TV instances.
    """
    _LOG.debug("Enter standby event: disconnecting device(s)")
    for configured in _configured_devices.values():
        await configured.disconnect()


@api.listens_to(ucapi.Events.EXIT_STANDBY)
async def on_r2_exit_standby() -> None:
    """
    Exit standby notification from Remote Two.

    Connect all LG TV instances.
    """
    _LOG.debug("Exit standby event: connecting device(s)")
    for configured in _configured_devices.values():
        # start background task
        try:
            await _LOOP.create_task(configured.connect())
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.error("Error while reconnecting to the LG TV %s", ex)
        # _LOOP.create_task(configured.connect())


@api.listens_to(ucapi.Events.SUBSCRIBE_ENTITIES)
async def on_subscribe_entities(entity_ids: list[str]) -> None:
    """
    Subscribe to given entities.

    :param entity_ids: entity identifiers.
    """
    _LOG.debug("Subscribe entities event: %s", entity_ids)
    for entity_id in entity_ids:
        entity = api.configured_entities.get(entity_id)
        device_id = device_from_entity_id(entity_id)
        if device_id in _configured_devices:
            device_config = _configured_devices[device_id]
            attributes = device_config.attributes
            if isinstance(entity, media_player.LGTVMediaPlayer):
                api.configured_entities.update_attributes(entity_id, attributes)
            if isinstance(entity, remote.LGRemote):
                api.configured_entities.update_attributes(
                    entity_id,
                    {
                        ucapi.remote.Attributes.STATE: remote.LG_REMOTE_STATE_MAPPING.get(
                            attributes.get(MediaAttr.STATE, States.UNKNOWN)
                        )
                    },
                )
            try:
                if not device_config.available:
                    await _LOOP.create_task(device_config.connect())
            except WEBOSTV_EXCEPTIONS as ex:
                _LOG.error("Error while reconnecting to the LG TV %s", ex)
            continue

        device_config = config.devices.get(device_id)
        if device_config:
            _configure_new_device(device_config, connect=True)
        else:
            _LOG.error("Failed to subscribe entity %s: no LG TV configuration found", entity_id)


@api.listens_to(ucapi.Events.UNSUBSCRIBE_ENTITIES)
async def on_unsubscribe_entities(entity_ids: list[str]) -> None:
    """On unsubscribe, we disconnect the objects and remove listeners for events."""
    _LOG.debug("Unsubscribe entities event: %s", entity_ids)
    devices_to_remove = set()
    for entity_id in entity_ids:
        device_id = device_from_entity_id(entity_id)
        if device_id is None:
            continue
        devices_to_remove.add(device_id)

    # Keep devices that are used by other configured entities not in this list
    for entity in api.configured_entities.get_all():
        entity_id = entity.get("entity_id")
        if entity_id in entity_ids:
            continue
        device_id = device_from_entity_id(entity_id)
        if device_id is None:
            continue
        if device_id in devices_to_remove:
            devices_to_remove.remove(device_id)

    for device_id in devices_to_remove:
        if device_id in _configured_devices:
            await _configured_devices[device_id].disconnect()
            _configured_devices[device_id].events.remove_all_listeners()


async def on_device_connected(device_id: str):
    """Handle device connection."""
    _LOG.debug("LG TV connected: %s", device_id)
    await api.set_device_state(ucapi.DeviceStates.CONNECTED)
    if device_id not in _configured_devices:
        _LOG.warning("LG TV %s is not configured", device_id)
        return

    for entity_id in _entities_from_device_id(device_id):
        configured_entity = api.configured_entities.get(entity_id)
        if configured_entity is None:
            _LOG.debug("Device connected : entity %s is not configured, ignoring it", entity_id)
            continue

        if configured_entity.entity_type == ucapi.EntityTypes.MEDIA_PLAYER:
            if (
                configured_entity.attributes[ucapi.media_player.Attributes.STATE]
                == ucapi.media_player.States.UNAVAILABLE
            ):
                api.configured_entities.update_attributes(
                    entity_id,
                    {ucapi.media_player.Attributes.STATE: ucapi.media_player.States.STANDBY},
                )
        elif configured_entity.entity_type == ucapi.EntityTypes.REMOTE:
            if configured_entity.attributes[ucapi.remote.Attributes.STATE] == ucapi.remote.States.UNAVAILABLE:
                api.configured_entities.update_attributes(
                    entity_id, {ucapi.remote.Attributes.STATE: ucapi.remote.States.OFF}
                )


async def on_device_disconnected(device_id: str):
    """Handle device disconnection."""
    _LOG.debug("LG TV disconnected: %s", device_id)

    for entity_id in _entities_from_device_id(device_id):
        configured_entity = api.configured_entities.get(entity_id)
        if configured_entity is None:
            continue

        if configured_entity.entity_type == ucapi.EntityTypes.MEDIA_PLAYER:
            api.configured_entities.update_attributes(
                entity_id,
                {ucapi.media_player.Attributes.STATE: ucapi.media_player.States.UNAVAILABLE},
            )
        elif configured_entity.entity_type == ucapi.EntityTypes.REMOTE:
            api.configured_entities.update_attributes(
                entity_id, {ucapi.remote.Attributes.STATE: ucapi.remote.States.UNAVAILABLE}
            )

    # TODO #20 when multiple devices are supported, the device state logic isn't that simple anymore!
    await api.set_device_state(ucapi.DeviceStates.DISCONNECTED)


async def on_device_connection_error(device_id: str, message):
    """Set entities of LG TV to state UNAVAILABLE if device connection error occurred."""
    _LOG.error(message)

    for entity_id in _entities_from_device_id(device_id):
        configured_entity = api.configured_entities.get(entity_id)
        if configured_entity is None:
            continue

        if configured_entity.entity_type == ucapi.EntityTypes.MEDIA_PLAYER:
            api.configured_entities.update_attributes(
                entity_id,
                {ucapi.media_player.Attributes.STATE: ucapi.media_player.States.UNAVAILABLE},
            )
        elif configured_entity.entity_type == ucapi.EntityTypes.REMOTE:
            api.configured_entities.update_attributes(
                entity_id, {ucapi.remote.Attributes.STATE: ucapi.remote.States.UNAVAILABLE}
            )

    # TODO #20 when multiple devices are supported, the device state logic isn't that simple anymore!
    await api.set_device_state(ucapi.DeviceStates.ERROR)


async def handle_device_address_change(device_id: str, address: str) -> None:
    """Update device configuration with changed IP address."""
    # TODO discover
    device = config.devices.get(device_id)
    if device and device.address != address:
        _LOG.info(
            "Updating IP address of configured LG TV %s: %s -> %s",
            device_id,
            device.address,
            address,
        )
        device.address = address
        config.devices.update(device)


async def on_device_update(device_id: str, update: dict[str, Any] | None) -> None:
    """
    Update attributes of configured media-player entity if device properties changed.

    :param device_id: device identifier
    :param update: dictionary containing the updated properties or None if
    """
    if update is None:
        if device_id not in _configured_devices:
            return
        device = _configured_devices[device_id]
        update = device.attributes
    else:
        _LOG.info("[%s] LG TV update: %s", device_id, update)

    attributes = None

    # TODO awkward logic: this needs better support from the integration library
    _LOG.info("Update device %s for configured devices %s", device_id, api.configured_entities)
    for entity_id in _entities_from_device_id(device_id):
        configured_entity = api.configured_entities.get(entity_id)
        if configured_entity is None:
            return

        if isinstance(configured_entity, media_player.LGTVMediaPlayer):
            attributes = configured_entity.filter_changed_attributes(update)
        elif isinstance(configured_entity, remote.LGRemote):
            attributes = configured_entity.filter_changed_attributes(update)

        if attributes:
            api.configured_entities.update_attributes(entity_id, attributes)


def _entities_from_device_id(device_id: str) -> list[str]:
    """
    Return all associated entity identifiers of the given device.

    :param device_id: the device identifier
    :return: list of entity identifiers
    """
    # dead simple for now: one media_player entity per device!
    # TODO #21 support multiple zones: one media-player per zone
    return [f"media_player.{device_id}", f"remote.{device_id}"]


def _configure_new_device(device_config: config.LGConfigDevice, connect: bool = True) -> None:
    """
    Create and configure a new device.

    Supported entities of the device are created and registered in the integration library as available entities.

    :param device_config: the receiver configuration.
    :param connect: True: start connection to receiver.
    """
    # the device may be already configured if the user changed settings of existing device
    if device_config.id in _configured_devices:
        _LOG.debug("Existing config device updated, update the running device %s", device_config)
        device = _configured_devices[device_config.id]
        device.update_config(device_config)
    else:
        device = lg.LGDevice(device_config, loop=_LOOP)

        _LOOP.create_task(on_device_connected(device.id))
        # device.events.on(lg.Events.CONNECTED, on_device_connected)
        # device.events.on(lg.Events.DISCONNECTED, on_device_disconnected)
        device.events.on(lg.Events.ERROR, on_device_connection_error)
        device.events.on(lg.Events.UPDATE, on_device_update)
        # TODO event change address
        # receiver.events.on(lg.Events.IP_ADDRESS_CHANGED, handle_lg_address_change)
        # receiver.connect()
        _configured_devices[device.id] = device

    if connect:
        # start background connection task
        try:
            _LOOP.create_task(device.connect())
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.debug(
                "Could not connect to device, probably because it is starting with magic packet %s",
                ex,
            )
    _register_available_entities(device_config, device)


def _register_available_entities(device_config: config.LGConfigDevice, device: lg.LGDevice) -> None:
    """
    Create entities for given receiver device and register them as available entities.

    :param device_config: Receiver
    """
    # plain and simple for now: only one media_player per device
    entities = [media_player.LGTVMediaPlayer(device_config, device), remote.LGRemote(device_config, device)]
    for entity in entities:
        if api.available_entities.contains(entity.id):
            api.available_entities.remove(entity.id)
        api.available_entities.add(entity)


def on_device_added(device: config.LGConfigDevice) -> None:
    """Handle a newly added device in the configuration."""
    _LOG.debug("New device added: %s", device)
    _configure_new_device(device, connect=False)


def on_device_updated(device: config.LGConfigDevice) -> None:
    """Handle an updated device in the configuration."""
    _LOG.debug("Device config updated: %s, reconnect with new configuration", device)
    _configure_new_device(device, connect=True)


def on_device_removed(device: config.LGConfigDevice | None) -> None:
    """Handle a removed device in the configuration."""
    if device is None:
        _LOG.debug("Configuration cleared, disconnecting & removing all configured LG TV instances")
        for configured in _configured_devices.values():
            _LOOP.create_task(_async_remove(configured))
        _configured_devices.clear()
        api.configured_entities.clear()
        api.available_entities.clear()
    else:
        if device.id in _configured_devices:
            _LOG.debug("Disconnecting from removed LG TV %s", device.id)
            configured = _configured_devices.pop(device.id)
            _LOOP.create_task(_async_remove(configured))
            for entity_id in _entities_from_device_id(configured.id):
                api.configured_entities.remove(entity_id)
                api.available_entities.remove(entity_id)


async def _async_remove(device: lg.LGDevice) -> None:
    """Disconnect from receiver and remove all listeners."""
    await device.disconnect()
    device.events.remove_all_listeners()


async def main():
    """Start the Remote Two integration driver."""
    logging.basicConfig()

    level = os.getenv("UC_LOG_LEVEL", "DEBUG").upper()
    logging.getLogger("lg").setLevel(level)
    # logging.getLogger("discover").setLevel(level)
    logging.getLogger("driver").setLevel(level)
    logging.getLogger("media_player").setLevel(level)
    logging.getLogger("config").setLevel(level)
    logging.getLogger("setup_flow").setLevel(level)

    config.devices = config.Devices(api.config_dir_path, on_device_added, on_device_removed, on_device_updated)
    for device_config in config.devices.all():
        _configure_new_device(device_config, connect=False)

    await _LOOP.create_task(config.devices.handle_address_change())

    await api.init("driver.json", setup_flow.driver_setup_handler)


if __name__ == "__main__":
    _LOOP.run_until_complete(main())
    _LOOP.run_forever()
