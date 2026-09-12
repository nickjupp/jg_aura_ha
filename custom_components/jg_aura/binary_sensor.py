"""Gateway health that stays readable when the gateway is not.

The zones go unavailable when the reflush nudge fails repeatedly, which is the
honest signal but a silent one: an entity that has vanished cannot say why it
went. This sensor is the counterpart -- it deliberately stays available while
the coordinator is failing, so there is always one entity left to ask.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import JgAuraConfigEntry, JgAuraCoordinator
from .entity import JgAuraGatewayEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JgAuraConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the gateway staleness sensor."""
    async_add_entities([JgAuraStaleBinarySensor(entry.runtime_data)])


class JgAuraStaleBinarySensor(JgAuraGatewayEntity, BinarySensorEntity):
    """On when the cloud's copy of the gateway can no longer be trusted."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "gateway_stale"

    def __init__(self, coordinator: JgAuraCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.data.device_id}_gateway_stale"

    @property
    def available(self) -> bool:
        """Always available, on purpose.

        CoordinatorEntity would mark this unavailable exactly when the
        coordinator starts failing -- which is the moment it has something to
        report. An instrument that switches off when the thing it measures goes
        wrong is the fault this whole entity exists to answer for.
        """
        return True

    @property
    def is_on(self) -> bool:
        """True from the first failed nudge, not from the third.

        The zones tolerate REFLUSH_FAILURE_LIMIT failures before going
        unavailable; this leads that by design, so the reason is already
        visible by the time they go.
        """
        return self.coordinator.client.reflush_failing

    @property
    def extra_state_attributes(self) -> dict[str, int]:
        return {"consecutive_failures": self.coordinator.client.reflush_failures}
