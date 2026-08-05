"""Shared entity base — device registry wiring for gateway and zones."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import ThermostatState
from .const import DOMAIN
from .coordinator import JgAuraCoordinator

MANUFACTURER = "Salus Controls / John Guest"
GATEWAY_MODEL = "JG Aura Hub (SALJG30)"
ZONE_MODEL = "JG Aura Wireless Thermostat"


class JgAuraGatewayEntity(CoordinatorEntity[JgAuraCoordinator]):
    """An entity belonging to the hub itself."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: JgAuraCoordinator) -> None:
        super().__init__(coordinator)
        snap = coordinator.data
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, snap.device_id)},
            manufacturer=MANUFACTURER,
            model=GATEWAY_MODEL,
            name=snap.group_name or "JG Aura Hub",
            sw_version=snap.gateway_version,
            serial_number=snap.serial,
        )


class JgAuraZoneEntity(CoordinatorEntity[JgAuraCoordinator]):
    """An entity belonging to one heating zone."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: JgAuraCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        state = self.zone
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.data.device_id}_{device_id}")},
            manufacturer=MANUFACTURER,
            model=ZONE_MODEL,
            name=state.name if state else f"Zone {device_id}",
            via_device=(DOMAIN, coordinator.data.device_id),
        )

    @property
    def zone(self) -> ThermostatState | None:
        return self.coordinator.data.thermostats.get(self._device_id)

    @property
    def available(self) -> bool:
        zone = self.zone
        return (
            super().available
            and self.coordinator.data.online
            and zone is not None
            and zone.available
        )
