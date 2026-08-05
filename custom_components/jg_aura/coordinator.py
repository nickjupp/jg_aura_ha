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
        self._pending_refresh: asyncio.Task[None] | None = None

    async def _async_update_data(self) -> GatewaySnapshot:
        try:
            return await self.client.async_get_snapshot()
        except JgAuraAuthError as err:
            # Surfaces as a reauth prompt rather than an endless retry loop.
            raise ConfigEntryAuthFailed(str(err)) from err
        except JgAuraError as err:
            raise UpdateFailed(str(err)) from err

    def schedule_refresh_after_write(self) -> None:
        """Queue a delayed re-poll, without blocking the caller.

        The cloud polls the gateway rather than being pushed to, so reading back
        immediately returns the pre-write value. Waiting inline for that settle
        made every service call outlast Home Assistant's state-verification
        window and emit "state change could not be verified within timeout",
        so the wait now runs as a background task instead.

        Coalescing: one pending refresh is enough. Several zones changed in
        quick succession share it, since the poll fetches all of them anyway.
        """
        if self._pending_refresh is not None and not self._pending_refresh.done():
            return
        assert self.config_entry is not None
        self._pending_refresh = self.config_entry.async_create_background_task(
            self.hass,
            self._delayed_refresh(),
            name=f"{DOMAIN}_post_write_refresh",
        )

    async def _delayed_refresh(self) -> None:
        await asyncio.sleep(POST_WRITE_REFRESH_DELAY)
        await self.async_request_refresh()
