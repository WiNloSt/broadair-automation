from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)

from .const import (
    DOMAIN,
    LEVEL,
    M3H_TO_SPEED,
    NORMAL_LEVEL,
    PRESET_AUTO,
    PRESET_NORMAL,
    SPEEDS,
)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BroadAirFan(coordinator, entry)])


class BroadAirFan(CoordinatorEntity, FanEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_translation_key = "purifier"
    _attr_preset_modes = [PRESET_AUTO, PRESET_NORMAL]
    _attr_speed_count = len(SPEEDS)
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.PRESET_MODE
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_fan"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Broad Air Purifier",
            "manufacturer": "Broad",
        }

    @property
    def is_on(self):
        return bool(self.coordinator.data.get("power_on"))

    @property
    def percentage(self):
        speed = M3H_TO_SPEED.get(self.coordinator.data.get("fan_m3h"))
        if not self.is_on or speed is None:
            return 0
        return ordered_list_item_to_percentage(SPEEDS, speed)

    @property
    def preset_mode(self):
        # read from the device: Auto when in auto, otherwise manual ("Normal")
        if not self.is_on:
            return None
        return PRESET_AUTO if self.coordinator.data.get("auto") else PRESET_NORMAL

    async def async_set_percentage(self, percentage):
        if percentage == 0:
            await self.async_turn_off()
            return
        speed = percentage_to_ordered_list_item(SPEEDS, percentage)
        await self.coordinator.command(f"/fan?level={LEVEL[speed]}")

    async def async_set_preset_mode(self, preset_mode):
        if preset_mode == PRESET_AUTO:
            await self.coordinator.command("/power?on=1")   # auto alone won't power on
            await self.coordinator.command("/auto")
        elif preset_mode == PRESET_NORMAL:
            await self.coordinator.command(f"/fan?level={NORMAL_LEVEL}")

    async def async_turn_on(self, percentage=None, preset_mode=None, **kwargs):
        if preset_mode:
            await self.async_set_preset_mode(preset_mode)
        elif percentage is not None:
            await self.async_set_percentage(percentage)
        else:
            await self.coordinator.command("/power?on=1")

    async def async_turn_off(self, **kwargs):
        await self.coordinator.command("/power?on=0")
