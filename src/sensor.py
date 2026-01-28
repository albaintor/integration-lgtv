"""
Media-player entity functions.

:copyright: (c) 2023 by Unfolded Circle ApS.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import logging
from typing import Any

import ucapi.media_player
from ucapi import EntityTypes, Sensor
from ucapi.media_player import States as MediaStates
from ucapi.sensor import Attributes, DeviceClasses, Options, States

import lg
from config import LGConfigDevice, LGEntity, create_entity_id
from const import LGSensors

_LOG = logging.getLogger(__name__)

SENSOR_STATE_MAPPING = {
    MediaStates.OFF: States.ON,
    MediaStates.ON: States.ON,
    MediaStates.STANDBY: States.ON,
    MediaStates.PLAYING: States.ON,
    MediaStates.PAUSED: States.ON,
    MediaStates.UNAVAILABLE: States.UNAVAILABLE,
    MediaStates.UNKNOWN: States.UNKNOWN,
}


# pylint: disable=R0917
class LGSensor(LGEntity, Sensor):
    """Representation of a Kodi Sensor entity."""

    ENTITY_NAME = "sensor"
    SENSOR_NAME: LGSensors

    def __init__(
        self,
        entity_id: str,
        name: str | dict[str, str],
        config_device: LGConfigDevice,
        device: lg.LGDevice,
        options: dict[Options, Any] | None = None,
        device_class: DeviceClasses = DeviceClasses.CUSTOM,
    ) -> None:
        """Initialize the class."""
        # pylint: disable = R0801
        self._device: lg.LGDevice = device
        features = []
        attributes = dict[Any, Any]()
        self._config_device = config_device
        self._device: lg.LGDevice = device
        self._state: States = States.UNAVAILABLE
        super().__init__(entity_id, name, features, attributes, device_class=device_class, options=options)

    @property
    def deviceid(self) -> str:
        """Return the device identifier."""
        return self._config_device.id

    @property
    def state(self) -> States:
        """Return sensor state."""
        raise self._state

    @property
    def sensor_value(self) -> str | float:
        """Return sensor value."""
        raise NotImplementedError()

    def update_attributes(self, update: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Return updated sensor value from full update if provided or sensor value if no udpate is provided."""
        attributes: dict[str, Any] = {}
        if update:
            if ucapi.media_player.Attributes.STATE in update:
                new_state = SENSOR_STATE_MAPPING.get(update[ucapi.media_player.Attributes.STATE])
                if new_state != self._state:
                    self._state = new_state
                    attributes[Attributes.STATE] = self._state
            if self.SENSOR_NAME in update:
                attributes[Attributes.VALUE] = update[self.SENSOR_NAME]
            return attributes
        return {
            Attributes.VALUE: self.sensor_value,
            Attributes.STATE: SENSOR_STATE_MAPPING.get(self._device.state),
        }


class LGSensorInputSource(LGSensor):
    """Current input source sensor entity."""

    ENTITY_NAME = "sensor_input_source"
    SENSOR_NAME = LGSensors.SENSOR_INPUT_SOURCE

    def __init__(self, config_device: LGConfigDevice, device: lg.LGDevice):
        """Initialize the class."""
        entity_id = f"{create_entity_id(config_device.id, EntityTypes.SENSOR)}.{self.ENTITY_NAME}"
        self._device = device
        self._config_device = config_device
        super().__init__(entity_id, {"en": "Input source", "fr": "Entrée source"}, config_device, device)

    @property
    def sensor_value(self) -> str | float:
        """Return sensor value."""
        return self._device.source if self._device.source else ""


class LGSensorVolume(LGSensor):
    """Current input source sensor entity."""

    ENTITY_NAME = "sensor_volume"
    SENSOR_NAME = LGSensors.SENSOR_VOLUME

    def __init__(self, config_device: LGConfigDevice, device: lg.LGDevice):
        """Initialize the class."""
        entity_id = f"{create_entity_id(config_device.id, EntityTypes.SENSOR)}.{self.ENTITY_NAME}"
        self._device = device
        self._config_device = config_device
        options = {
            Options.CUSTOM_UNIT: "%",
            Options.MIN_VALUE: 0,
            Options.MAX_VALUE: 100,
        }
        super().__init__(entity_id, {"en": "Volume", "fr": "Volume"}, config_device, device, options)

    @property
    def sensor_value(self) -> str | float:
        """Return sensor value."""
        return self._device.volume_level if self._device.volume_level else 0


class LGSensorMuted(LGSensor):
    """Current mute state sensor entity."""

    ENTITY_NAME = "sensor_muted"
    SENSOR_NAME = LGSensors.SENSOR_MUTED

    def __init__(self, config_device: LGConfigDevice, device: lg.LGDevice):
        """Initialize the class."""
        entity_id = f"{create_entity_id(config_device.id, EntityTypes.SENSOR)}.{self.ENTITY_NAME}"
        self._device = device
        self._config_device = config_device
        super().__init__(
            entity_id, {"en": "Muted", "fr": "Son coupé"}, config_device, device, None, DeviceClasses.BINARY
        )

    @property
    def sensor_value(self) -> str | float:
        """Return sensor value."""
        return "on" if self._device.is_volume_muted else "off"


class LGSensorSoundOutput(LGSensor):
    """Current sound output sensor entity."""

    ENTITY_NAME = "sensor_sound_output"
    SENSOR_NAME = LGSensors.SENSOR_SOUND_OUTPUT

    def __init__(self, config_device: LGConfigDevice, device: lg.LGDevice):
        """Initialize the class."""
        entity_id = f"{create_entity_id(config_device.id, EntityTypes.SENSOR)}.{self.ENTITY_NAME}"
        self._device = device
        self._config_device = config_device
        super().__init__(entity_id, {"en": "Sound output", "fr": "Sortie audio"}, config_device, device)

    @property
    def sensor_value(self) -> str | float:
        """Return sensor value."""
        return self._device.sound_output if self._device.sound_output else ""
