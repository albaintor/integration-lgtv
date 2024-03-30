#!/usr/bin/env python3
"""
This module implements a Remote Two integration driver for Sony AVR receivers.

:copyright: (c) 2023 by Unfolded Circle ApS.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import asyncio
import logging
import os
from typing import Any

from const import WEBOSTV_EXCEPTIONS

import lg
import config
import media_player
import setup_flow
import ucapi
from config import device_from_entity_id
from ucapi.media_player import Attributes as MediaAttr

_LOG = logging.getLogger("driver")  # avoid having __main__ in log messages
_LOOP = asyncio.get_event_loop()

# Global variables
api = ucapi.IntegrationAPI(_LOOP)
# Map of id -> LG instance
_configured_lgtvs: dict[str, lg.LGDevice] = {}
_R2_IN_STANDBY = False


# async def receiver_status_poller(interval: float = 10.0) -> None:
#     """Receiver data poller."""
#     while True:
#         await asyncio.sleep(interval)
#         if _R2_IN_STANDBY:
#             continue
#         try:
#             for receiver in _configured_avrs.values():
#                 if not receiver.active:
#                     continue
#                 # TODO #20  run in parallel, join, adjust interval duration based on execution time for next update
#                 await receiver.async_update_receiver_data()
#         except (KeyError, ValueError):  # TODO check parallel access / modification while iterating a dict
#             pass


@api.listens_to(ucapi.Events.CONNECT)
async def on_r2_connect_cmd() -> None:
    """Connect all configured TVs when the Remote Two sends the connect command."""
    # TODO check if we were in standby and ignore the call? We'll also get an EXIT_STANDBY
    _LOG.debug("R2 connect command: connecting device(s)")
    for device in _configured_lgtvs.values():
        # start background task
        # TODO ? what is the connect event for (against exit from standby)
        # await _LOOP.create_task(device.power_on())
        try:
            await _LOOP.create_task(device.connect())
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.debug("Could not connect to device, probably because it is starting with magic packet %s", ex)


@api.listens_to(ucapi.Events.DISCONNECT)
async def on_r2_disconnect_cmd():
    """Disconnect all configured TVs when the Remote Two sends the disconnect command."""
    for device in _configured_lgtvs.values():
        # start background task
        await _LOOP.create_task(device.disconnect())


@api.listens_to(ucapi.Events.ENTER_STANDBY)
async def on_r2_enter_standby() -> None:
    """
    Enter standby notification from Remote Two.

    Disconnect every Sony AVR instances.
    """
    global _R2_IN_STANDBY

    _R2_IN_STANDBY = True
    _LOG.debug("Enter standby event: disconnecting device(s)")
    for configured in _configured_lgtvs.values():
        await configured.disconnect()


@api.listens_to(ucapi.Events.EXIT_STANDBY)
async def on_r2_exit_standby() -> None:
    """
    Exit standby notification from Remote Two.

    Connect all Sony AVR instances.
    """
    global _R2_IN_STANDBY

    _R2_IN_STANDBY = False
    _LOG.debug("Exit standby event: connecting device(s)")

    for configured in _configured_lgtvs.values():
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
    global _R2_IN_STANDBY

    _R2_IN_STANDBY = False
    _LOG.debug("Subscribe entities event: %s", entity_ids)
    for entity_id in entity_ids:
        device_id = device_from_entity_id(entity_id)
        if device_id in _configured_lgtvs:
            device = _configured_lgtvs[device_id]
            state = lg.LG_STATE_MAPPING.get(device.state)
            api.configured_entities.update_attributes(entity_id, {ucapi.media_player.Attributes.STATE: state})
            continue

        device = config.devices.get(device_id)
        if device:
            _configure_new_device(device, connect=True)
        else:
            _LOG.error("Failed to subscribe entity %s: no AVR configuration found", entity_id)


@api.listens_to(ucapi.Events.UNSUBSCRIBE_ENTITIES)
async def on_unsubscribe_entities(entity_ids: list[str]) -> None:
    """On unsubscribe, we disconnect the objects and remove listeners for events."""
    _LOG.debug("Unsubscribe entities event: %s", entity_ids)
    for entity_id in entity_ids:
        device_id = device_from_entity_id(entity_id)
        if device_id is None:
            continue
        if device_id in _configured_lgtvs:
            # TODO #21 this doesn't work once we have more than one entity per device!
            # --- START HACK ---
            # Since an AVR instance only provides exactly one media-player, it's save to disconnect if the entity is
            # unsubscribed. This should be changed to a more generic logic, also as template for other integrations!
            # Otherwise this sets a bad copy-paste example and leads to more issues in the future.
            # --> correct logic: check configured_entities, if empty: disconnect
            await _configured_lgtvs[entity_id].disconnect()
            _configured_lgtvs[entity_id].events.remove_all_listeners()


async def on_device_connected(device_id: str):
    """Handle device connection."""
    _LOG.debug("LG TV connected: %s", device_id)

    if device_id not in _configured_lgtvs:
        _LOG.warning("LG TV %s is not configured", device_id)
        return

    # TODO #20 when multiple devices are supported, the device state logic isn't that simple anymore!
    await api.set_device_state(ucapi.DeviceStates.CONNECTED)

    for entity_id in _entities_from_device_id(device_id):
        configured_entity = api.configured_entities.get(entity_id)
        if configured_entity is None:
            continue

        if configured_entity.entity_type == ucapi.EntityTypes.MEDIA_PLAYER:
            if (
                configured_entity.attributes[ucapi.media_player.Attributes.STATE]
                == ucapi.media_player.States.UNAVAILABLE
            ):
                # TODO why STANDBY?
                api.configured_entities.update_attributes(
                    entity_id, {ucapi.media_player.Attributes.STATE: ucapi.media_player.States.STANDBY}
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
                entity_id, {ucapi.media_player.Attributes.STATE: ucapi.media_player.States.UNAVAILABLE}
            )

    # TODO #20 when multiple devices are supported, the device state logic isn't that simple anymore!
    await api.set_device_state(ucapi.DeviceStates.DISCONNECTED)


async def on_device_connection_error(device_id: str, message):
    """Set entities of LG TV to state UNAVAILABLE if AVR connection error occurred."""
    _LOG.error(message)

    for entity_id in _entities_from_device_id(device_id):
        configured_entity = api.configured_entities.get(entity_id)
        if configured_entity is None:
            continue

        if configured_entity.entity_type == ucapi.EntityTypes.MEDIA_PLAYER:
            api.configured_entities.update_attributes(
                entity_id, {ucapi.media_player.Attributes.STATE: ucapi.media_player.States.UNAVAILABLE}
            )

    # TODO #20 when multiple devices are supported, the device state logic isn't that simple anymore!
    await api.set_device_state(ucapi.DeviceStates.ERROR)


async def handle_device_address_change(device_id: str, address: str) -> None:
    """Update device configuration with changed IP address."""
    # TODO discover
    device = config.devices.get(device_id)
    if device and device.address != address:
        _LOG.info("Updating IP address of configured AVR %s: %s -> %s", device_id, device.address, address)
        device.address = address
        config.devices.update(device)


async def on_device_update(device_id: str, update: dict[str, Any] | None) -> None:
    """
    Update attributes of configured media-player entity if AVR properties changed.

    :param device_id: device identifier
    :param update: dictionary containing the updated properties or None if
    """
    if update is None:
        if device_id not in _configured_lgtvs:
            return
        receiver = _configured_lgtvs[device_id]
        update = {
            MediaAttr.STATE: receiver.state,
            MediaAttr.MEDIA_IMAGE_URL: receiver.media_image_url,
            MediaAttr.MEDIA_TITLE: receiver.media_title,
            MediaAttr.MUTED: receiver.is_volume_muted,
            MediaAttr.SOURCE: receiver.source,
            MediaAttr.SOURCE_LIST: receiver.source_list,
            MediaAttr.VOLUME: receiver.volume_level,
        }
    else:
        _LOG.info("[%s] LG TV update: %s", device_id, update)

    attributes = None

    # TODO awkward logic: this needs better support from the integration library
    for entity_id in _entities_from_device_id(device_id):
        configured_entity = api.configured_entities.get(entity_id)
        if configured_entity is None:
            return

        if isinstance(configured_entity, media_player.LGTVMediaPlayer):
            attributes = configured_entity.filter_changed_attributes(update)

        if attributes:
            # _LOG.debug("LG TV send updated attributes %s %s", entity_id, attributes)
            api.configured_entities.update_attributes(entity_id, attributes)


def _entities_from_device_id(device_id: str) -> list[str]:
    """
    Return all associated entity identifiers of the given device.

    :param device_id: the AVR identifier
    :return: list of entity identifiers
    """
    # dead simple for now: one media_player entity per device!
    # TODO #21 support multiple zones: one media-player per zone
    return [f"media_player.{device_id}"]


def _configure_new_device(device_config: config.LGConfigDevice, connect: bool = True) -> None:
    """
    Create and configure a new AVR device.

    Supported entities of the device are created and registered in the integration library as available entities.

    :param device: the receiver configuration.
    :param connect: True: start connection to receiver.
    """
    # the device should not yet be configured, but better be safe
    if device_config.id in _configured_lgtvs:
        device = _configured_lgtvs[device_config.id]
        device.disconnect()
    else:
        device = lg.LGDevice(device_config, loop=_LOOP)

        device.events.on(lg.Events.CONNECTED, on_device_connected)
        device.events.on(lg.Events.DISCONNECTED, on_device_disconnected)
        device.events.on(lg.Events.ERROR, on_device_connection_error)
        device.events.on(lg.Events.UPDATE, on_device_update)
        # TODO event change address
        # receiver.events.on(avr.Events.IP_ADDRESS_CHANGED, handle_avr_address_change)
        # receiver.connect()
        _configured_lgtvs[device.id] = device

    if connect:
        # start background connection task
        try:
            _LOOP.create_task(device.connect())
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.debug("Could not connect to device, probably because it is starting with magic packet %s", ex)

    _register_available_entities(device_config, device)


def _register_available_entities(device_config: config.LGConfigDevice, device: lg.LGDevice) -> None:
    """
    Create entities for given receiver device and register them as available entities.

    :param device_config: Receiver
    """
    # plain and simple for now: only one media_player per AVR device
    # entity = media_player.create_entity(device)
    entity = media_player.LGTVMediaPlayer(device_config, device)

    if api.available_entities.contains(entity.id):
        api.available_entities.remove(entity.id)
    api.available_entities.add(entity)


def on_device_added(device: config.LGConfigDevice) -> None:
    """Handle a newly added device in the configuration."""
    _LOG.debug("New device added: %s", device)
    _configure_new_device(device, connect=False)


def on_device_removed(device: config.LGConfigDevice | None) -> None:
    """Handle a removed device in the configuration."""
    if device is None:
        _LOG.debug("Configuration cleared, disconnecting & removing all configured AVR instances")
        for configured in _configured_lgtvs.values():
            _LOOP.create_task(_async_remove(configured))
        _configured_lgtvs.clear()
        api.configured_entities.clear()
        api.available_entities.clear()
    else:
        if device.id in _configured_lgtvs:
            _LOG.debug("Disconnecting from removed AVR %s", device.id)
            configured = _configured_lgtvs.pop(device.id)
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
    logging.getLogger("avr").setLevel(level)
    logging.getLogger("discover").setLevel(level)
    logging.getLogger("driver").setLevel(level)
    logging.getLogger("media_player").setLevel(level)
    logging.getLogger("receiver").setLevel(level)
    logging.getLogger("setup_flow").setLevel(level)

    config.devices = config.Devices(api.config_dir_path, on_device_added, on_device_removed)
    for device_config in config.devices.all():
        _configure_new_device(device_config, connect=False)

    # _LOOP.create_task(receiver_status_poller())
    for device in _configured_lgtvs.values():
        if not device.available:
            continue
        try:
            await _LOOP.create_task(device.connect())
        except WEBOSTV_EXCEPTIONS as ex:
            _LOG.debug("Could not connect to device, probably because it is starting with magic packet %s", ex)

    await api.init("driver.json", setup_flow.driver_setup_handler)


if __name__ == "__main__":
    _LOOP.run_until_complete(main())
    _LOOP.run_forever()
