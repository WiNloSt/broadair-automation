from homeassistant.const import Platform

from .const import DOMAIN
from .coordinator import BroadAirCoordinator

PLATFORMS = [Platform.FAN, Platform.SENSOR]


async def async_setup_entry(hass, entry):
    coordinator = BroadAirCoordinator(hass, entry.data["host"], entry.data["port"])
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass, entry):
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded
