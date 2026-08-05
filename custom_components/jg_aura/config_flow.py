"""Config, reauth, reconfigure and options flows."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .api import (
    JgAuraAuthError,
    JgAuraClient,
    JgAuraConnectionError,
    JgAuraError,
)
from .const import (
    CONF_HOST,
    CONF_SCAN_INTERVAL,
    DEFAULT_HOST,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .coordinator import JgAuraConfigEntry

_LOGGER = logging.getLogger(__name__)

STEP_USER = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_HOST, default=DEFAULT_HOST): str,
    }
)


async def _validate(hass, email: str, password: str, host: str) -> tuple[str, str]:
    """Log in and locate the gateway. Returns (gateway_id, password_hash)."""
    client = JgAuraClient(
        session=async_get_clientsession(hass),
        host=host,
        email=email,
        password=password,
    )
    await client.login()
    assert client.gateway_id is not None
    return client.gateway_id, client.password_hash


class JgAuraConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                gateway_id, pw_hash = await _validate(
                    self.hass,
                    user_input[CONF_EMAIL],
                    user_input[CONF_PASSWORD],
                    user_input[CONF_HOST],
                )
            except JgAuraAuthError:
                errors["base"] = "invalid_auth"
            except JgAuraConnectionError:
                errors["base"] = "cannot_connect"
            except JgAuraError:
                errors["base"] = "unknown"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("unexpected error validating JG Aura credentials")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(gateway_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"JG Aura ({gateway_id})",
                    data={
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        # Only the MD5 hash is stored -- it is what the API
                        # takes, so the plaintext password is never persisted.
                        "password_hash": pw_hash,
                        CONF_HOST: user_input[CONF_HOST],
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                gateway_id, pw_hash = await _validate(
                    self.hass,
                    entry.data[CONF_EMAIL],
                    user_input[CONF_PASSWORD],
                    entry.data[CONF_HOST],
                )
            except JgAuraAuthError:
                errors["base"] = "invalid_auth"
            except JgAuraConnectionError:
                errors["base"] = "cannot_connect"
            except JgAuraError:
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(gateway_id)
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry, data_updates={"password_hash": pw_hash}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                gateway_id, pw_hash = await _validate(
                    self.hass,
                    user_input[CONF_EMAIL],
                    user_input[CONF_PASSWORD],
                    user_input[CONF_HOST],
                )
            except JgAuraAuthError:
                errors["base"] = "invalid_auth"
            except JgAuraConnectionError:
                errors["base"] = "cannot_connect"
            except JgAuraError:
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(gateway_id)
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        "password_hash": pw_hash,
                        CONF_HOST: user_input[CONF_HOST],
                    },
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL, default=entry.data[CONF_EMAIL]): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Optional(CONF_HOST, default=entry.data[CONF_HOST]): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: JgAuraConfigEntry) -> OptionsFlow:
        return JgAuraOptionsFlow()


class JgAuraOptionsFlow(OptionsFlow):
    """Polling interval only -- the cloud is undocumented, so keep a floor on it."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_SCAN_INTERVAL, default=current): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            max=MAX_SCAN_INTERVAL,
                            step=10,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    )
                }
            ),
        )
