from datetime import timedelta

import async_timeout
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, LOGGER


class BroadAirCoordinator(DataUpdateCoordinator):
    """Polls the add-on's /status and issues control commands to it."""

    def __init__(self, hass, host, port):
        super().__init__(hass, LOGGER, name=DOMAIN,
                         update_interval=timedelta(seconds=10))
        self._base = f"http://{host}:{port}"
        self._session = async_get_clientsession(hass)

    async def _async_update_data(self):
        try:
            async with async_timeout.timeout(8):
                async with self._session.get(f"{self._base}/status") as r:
                    return await r.json()
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(err) from err

    async def command(self, path):
        """GET a control endpoint (e.g. /fan?level=2) then refresh."""
        async with async_timeout.timeout(8):
            await self._session.get(f"{self._base}{path}")
        await self.async_request_refresh()
