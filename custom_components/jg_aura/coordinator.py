"""Single shared polling coordinator for the JG Aura gateway."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GatewaySnapshot, JgAuraAuthError, JgAuraClient, JgAuraError
from .const import (
    CONF_HOST,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    POST_WRITE_REFRESH_DELAY,
)

_LOGGER = logging.getLogger(__name__)

# Plain alias rather than a PEP 695 `type` statement so the module also imports
# under older interpreters during offline linting.
JgAuraConfigEntry = ConfigEntry["JgAuraCoordinator"]


class JgAuraCoordinator(DataUpdateCoordinator[GatewaySnapshot]):
    """One coordinator, one client, one request per poll.

    The upstream integration ran a separate client and coordinator per platform
    at 2 s and 5 s intervals, each poll costing two requests -- roughly 50
    requests a minute against an undocumented cloud. This does one.
    """

    def __init__(self, hass: HomeAssistant, entry: JgAuraConfigEntry) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
            config_entry=entry,
        )
        self.client = JgAuraClient(
            session=async_get_clientsession(hass),
            host=entry.data[CONF_HOST],
            email=entry.data["email"],
            password_hash=entry.data["password_hash"],
        )

    async def _async_update_data(self) -> GatewaySnapshot:
        try:
            return await self.client.async_get_snapshot()
        except JgAuraAuthError as err:
            # Surfaces as a reauth prompt rather than an endless retry loop.
            raise ConfigEntryAuthFailed(str(err)) from err
        except JgAuraError as err:
            raise UpdateFailed(str(err)) from err

    async def async_refresh_after_write(self) -> None:
        """Re-poll once the gateway has had time to apply a command.

        The cloud polls the gateway rather than being pushed to, so reading back
        immediately returns the pre-write value.
        """
        await asyncio.sleep(POST_WRITE_REFRESH_DELAY)
        await self.async_request_refresh()
