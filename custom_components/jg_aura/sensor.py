"""Diagnostic sensors for the gateway itself."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant

from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import GatewaySnapshot
from .coordinator import JgAuraConfigEntry, JgAuraCoordinator
from .entity import JgAuraGatewayEntity


@dataclass(frozen=True, kw_only=True)
class JgAuraSensorDescription(SensorEntityDescription):
    """A gateway sensor and how to read it from a snapshot."""

    value_fn: Callable[[GatewaySnapshot], str | int | None]


SENSORS: tuple[JgAuraSensorDescription, ...] = (
    JgAuraSensorDescription(
        key="zones",
        translation_key="zones",
        icon="mdi:radiator",
        value_fn=lambda s: len(s.thermostats),
    ),
    JgAuraSensorDescription(
        key="zones_online",
        translation_key="zones_online",
        icon="mdi:radiator-disabled",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: sum(1 for t in s.thermostats.values() if t.available),
    ),
    JgAuraSensorDescription(
        key="it600_version",
        translation_key="it600_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.it600_version,
    ),
    JgAuraSensorDescription(
        key="error_message",
        translation_key="error_message",
        icon="mdi:alert-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.error_message or "none",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JgAuraConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up gateway sensors."""
    coordinator = entry.runtime_data
    async_add_entities(JgAuraSensor(coordinator, d) for d in SENSORS)


class JgAuraSensor(JgAuraGatewayEntity, SensorEntity):
    """A read-only value from the gateway."""

    entity_description: JgAuraSensorDescription

    def __init__(
        self, coordinator: JgAuraCoordinator, description: JgAuraSensorDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.data.device_id}_{description.key}"

    @property
    def native_value(self) -> str | int | None:
        return self.entity_description.value_fn(self.coordinator.data)
