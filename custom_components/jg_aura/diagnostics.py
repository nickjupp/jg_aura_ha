"""Diagnostics dump, with credentials and identifiers redacted."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import JgAuraConfigEntry

REDACT = {"password_hash", "email", "serial"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: JgAuraConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    snap = entry.runtime_data.data
    return {
        "entry": async_redact_data(dict(entry.data), REDACT),
        "options": dict(entry.options),
        "gateway": {
            "online": snap.online,
            "group_name": snap.group_name,
            "it600_version": snap.it600_version,
            "gateway_version": snap.gateway_version,
            "error_message": snap.error_message,
            "has_hot_water": snap.has_hot_water,
        },
        "zones": {
            zone_id: {
                "name": zone.name,
                "available": zone.available,
                "mode_index": zone.mode_index,
                "mode": zone.detail,
                "preset": zone.preset,
                "status_flag": zone.status_flag,
                "current_temperature": zone.current_temperature,
                "target_temperature": zone.target_temperature,
                "heat_demand": zone.heat_demand,
            }
            for zone_id, zone in snap.thermostats.items()
        },
        # The raw blobs, so a future decoding question can be answered without
        # asking the user to run a probe script again.
        "raw": {
            name: snap.raw_attributes[name].value
            for name in ("001", "S01", "S02", "S03", "B05", "B06", "B07")
            if name in snap.raw_attributes
        },
    }
