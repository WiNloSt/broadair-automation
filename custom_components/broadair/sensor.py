from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

# key, name, device_class, unit
SENSORS = [
    ("pm25", "PM2.5", SensorDeviceClass.PM25, "µg/m³"),
    ("temp_c", "Temperature", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
    ("fan_m3h", "Airflow", None, "m³/h"),
]


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(BroadAirSensor(coordinator, entry, *s) for s in SENSORS)


class BroadAirSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry, key, name, device_class, unit):
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Broad Air Purifier",
            "manufacturer": "Broad",
        }

    @property
    def native_value(self):
        return self.coordinator.data.get(self._key)
