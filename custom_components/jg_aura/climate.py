"""Climate entities — one per live JG Aura heating zone."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import JgAuraError
from .const import (
    MAX_TEMP,
    MIN_TEMP,
    MODE_WRITE_MAP,
    PRESET_MODES,
    TEMP_STEP,
)
from .coordinator import JgAuraConfigEntry, JgAuraCoordinator
from .entity import JgAuraZoneEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JgAuraConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create one climate entity per zone in the summary blob.

    Iterating the summary rather than the name list is deliberate: the gateway's
    name list keeps entries for long-removed thermostats, and indexing from it
    into the summary is what makes the upstream integration raise IndexError.
    """
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync() -> None:
        new = [
            JgAuraClimate(coordinator, device_id)
            for device_id in coordinator.data.thermostats
            if device_id not in known
        ]
        if new:
            known.update(entity.device_id for entity in new)
            async_add_entities(new)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


class JgAuraClimate(JgAuraZoneEntity, ClimateEntity):
    """A single underfloor heating zone."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_hvac_mode = HVACMode.HEAT
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_target_temperature_step = TEMP_STEP
    _attr_name = None  # the device carries the name

    # Presets are readable in full; writes are restricted to the two indices
    # captured from the JG Aura app itself (see const.MODE_WRITE_MAP). Selecting
    # an unverified preset raises rather than sending a guessed value.
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    )
    _attr_preset_modes = PRESET_MODES

    def __init__(self, coordinator: JgAuraCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{coordinator.data.device_id}_{device_id}"
        # Shown immediately after a write so the UI doesn't sit on the old value
        # for the ~6 s the gateway takes to report it back. Cleared on the next
        # coordinator update, whatever it says — so a write that silently failed
        # reverts visibly rather than being masked.
        self._optimistic_target: float | None = None
        self._optimistic_preset: str | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        self._optimistic_target = None
        self._optimistic_preset = None
        super()._handle_coordinator_update()

    @property
    def device_id(self) -> str:
        return self._device_id

    @property
    def current_temperature(self) -> float | None:
        zone = self.zone
        return zone.current_temperature if zone else None

    @property
    def target_temperature(self) -> float | None:
        if self._optimistic_target is not None:
            return self._optimistic_target
        zone = self.zone
        return zone.target_temperature if zone else None

    @property
    def preset_mode(self) -> str | None:
        if self._optimistic_preset is not None:
            return self._optimistic_preset
        zone = self.zone
        return zone.preset if zone else None

    @property
    def hvac_action(self) -> HVACAction | None:
        zone = self.zone
        if zone is None or zone.heat_demand is None:
            return None
        # The mode index's upper bank is the heat-demand flag — verified on live
        # hardware, see const.MODE_BANK_SIZE.
        return HVACAction.HEATING if zone.heat_demand else HVACAction.IDLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        zone = self.zone
        if zone is None:
            return {}
        return {
            "jg_device_id": zone.device_id,
            "jg_preset": zone.preset,
            "jg_mode": zone.detail,
            "jg_mode_index": zone.mode_index,
            "jg_status_flag": zone.status_flag,
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        try:
            await self.coordinator.client.async_set_temperature(
                self._device_id, float(temperature)
            )
        except (JgAuraError, ValueError) as err:
            raise HomeAssistantError(
                f"could not set {self.name or self._device_id} to {temperature}: {err}"
            ) from err
        self._optimistic_target = float(temperature)
        self.async_write_ha_state()
        self.coordinator.schedule_refresh_after_write()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        index = MODE_WRITE_MAP.get(preset_mode)
        if index is None:
            raise HomeAssistantError(
                f"{preset_mode!r} cannot be set from Home Assistant yet: the mode "
                "index the JG Aura app writes for it has not been observed, and "
                "guessing would put the zone on the wrong setpoint band. "
                f"Settable presets: {', '.join(sorted(MODE_WRITE_MAP))}. "
                "Use the JG Aura app for the others."
            )
        try:
            await self.coordinator.client.async_set_mode_index(self._device_id, index)
        except (JgAuraError, ValueError) as err:
            raise HomeAssistantError(
                f"could not set {self.name or self._device_id} to {preset_mode}: {err}"
            ) from err
        self._optimistic_preset = preset_mode
        self.async_write_ha_state()
        self.coordinator.schedule_refresh_after_write()
