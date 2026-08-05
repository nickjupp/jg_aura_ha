"""The JG Aura (Salus iT600 / Arrayent cloud) integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import JgAuraConfigEntry, JgAuraCoordinator

PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: JgAuraConfigEntry) -> bool:
    """Set up from a config entry."""
    coordinator = JgAuraCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: JgAuraConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: JgAuraConfigEntry) -> None:
    """Reload when options (e.g. the poll interval) change."""
    await hass.config_entries.async_reload(entry.entry_id)
