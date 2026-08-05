"""Async client and wire-format decoder for the JG Aura (Salus iT600 / Arrayent) cloud.

Deliberately free of Home Assistant imports so the decoding logic can be unit
tested against captured gateway payloads.

Security note: every request carries the MD5 password hash and the session token
in its query string -- that is the Arrayent API's design, not a choice. No URL is
ever logged, and `_safe` scrubs anything token-shaped before it reaches a log
record or an exception message.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import aiohttp

from .const import (
    APP_ID,
    ATTR_DISPLAY_LOCATION,
    ATTR_REFLUSH,
    ATTR_HW_DEVICE_SETTING,
    ATTR_NAMES_HIGH,
    ATTR_NAMES_LOW,
    ATTR_ONLINE,
    ATTR_SET_MODE,
    ATTR_SET_SETPOINT,
    ATTR_SUMMARY,
    CHAR_OFFSET,
    MAX_TEMP,
    MIN_TEMP,
    MODE_BANK_SIZE,
    MODE_KEY_TO_PRESET,
    MODE_WRITE_WIDTH,
    OFFLINE_TEMP_SENTINEL,
    SUB_MODE_DETAIL,
    SUB_MODE_MAP,
    SUMMARY_ID_LEN,
    REFLUSH_SETTLE,
    SUMMARY_RECORD_LEN,
    SUMMARY_TERMINATOR,
    TEMP_STEP,
    WRITE_PREFIX,
)

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 20


class JgAuraError(Exception):
    """Base error."""


class JgAuraConnectionError(JgAuraError):
    """The cloud could not be reached."""


class JgAuraAuthError(JgAuraError):
    """Credentials were rejected, or the session is no longer valid."""


class JgAuraResponseError(JgAuraError):
    """The cloud replied with something we could not use."""


_SCRUB = re.compile(r"(secToken=|password=)[^&\s]+")


def _safe(text: str) -> str:
    """Strip credentials from anything destined for a log or an exception."""
    return _SCRUB.sub(r"\1<redacted>", text)


def _local(tag: str) -> str:
    """Strip the XML namespace from a tag name."""
    return tag.split("}")[-1]


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Attribute:
    """One entry from the gateway's self-describing attribute table."""

    id: str
    name: str
    display_name: str
    value: str
    upd_time: str = ""


@dataclass(frozen=True)
class ThermostatState:
    """Decoded state for a single zone."""

    device_id: str
    name: str
    status_flag: int
    mode_index: int
    current_temperature: float | None
    target_temperature: float | None
    available: bool
    mode_key: str
    detail: str
    preset: str | None
    heat_demand: bool | None  # from the mode index's upper bank -- see const.MODE_BANK_SIZE

    @property
    def unique_suffix(self) -> str:
        return self.device_id


@dataclass
class GatewaySnapshot:
    """Everything one poll yields."""

    device_id: str
    online: bool
    group_name: str | None
    it600_version: str | None
    gateway_version: str | None
    serial: str | None
    error_message: str | None
    has_hot_water: bool
    thermostats: dict[str, ThermostatState] = field(default_factory=dict)
    raw_attributes: dict[str, Attribute] = field(default_factory=dict)


def parse_attributes(xml_text: str) -> dict[str, Attribute]:
    """Build a name -> Attribute map from a getDeviceAttributesWithValues body."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as err:
        raise JgAuraResponseError(f"attribute table was not valid XML: {err}") from err

    out: dict[str, Attribute] = {}
    for element in root.iter():
        if _local(element.tag) != "attrList":
            continue
        fields = {_local(child.tag): (child.text or "") for child in element}
        name = fields.get("name", "").strip()
        if not name:
            continue
        out[name] = Attribute(
            id=fields.get("id", "").strip(),
            name=name,
            display_name=fields.get("displayName", "").strip(),
            # A global attribute carries its payload in attrValue as well; value
            # has been identical in every sample, but prefer value and fall back.
            value=fields.get("value") or fields.get("attrValue", ""),
            upd_time=fields.get("updTime", "").strip(),
        )
    if not out:
        raise JgAuraResponseError("attribute table contained no named attributes")
    return out


def parse_device_names(*values: str) -> dict[str, str]:
    """Decode the comma-separated `<4-char id><friendly name>` name lists.

    Accepts S02 and S03 together. Entries are historical and routinely contain
    ids that no longer exist -- callers must treat this as a lookup table, never
    as the list of live devices.
    """
    names: dict[str, str] = {}
    for value in values:
        if not value:
            continue
        for token in value.split(","):
            token = token.strip()
            if len(token) <= SUMMARY_ID_LEN:
                continue
            device_id = token[:SUMMARY_ID_LEN].lower()
            label = token[SUMMARY_ID_LEN:].strip()
            if label:
                names[device_id] = label
    return names


def _decode_temp(char: str) -> float:
    return (ord(char) - CHAR_OFFSET) * TEMP_STEP


def parse_summary(value: str, names: dict[str, str] | None = None) -> dict[str, ThermostatState]:
    """Decode the summary blob into live zones.

    This is the authoritative device list. Iterating the *name* list instead and
    indexing into here is what breaks the upstream integration: name lists
    outlive the devices they describe.
    """
    names = names or {}
    states: dict[str, ThermostatState] = {}
    if not value:
        return states

    for offset in range(0, len(value), SUMMARY_RECORD_LEN):
        record = value[offset : offset + SUMMARY_RECORD_LEN]
        if len(record) < SUMMARY_RECORD_LEN:
            break  # trailing '~' or a partial record -- end of list
        device_id = record[:SUMMARY_ID_LEN].lower()
        if device_id == SUMMARY_TERMINATOR:
            break
        state_chars = record[SUMMARY_ID_LEN:]

        try:
            status_flag = ord(state_chars[0]) - CHAR_OFFSET
            mode_index = ord(state_chars[1]) - CHAR_OFFSET
            current = _decode_temp(state_chars[2])
            target = _decode_temp(state_chars[3])
        except (IndexError, TypeError):  # pragma: no cover - defensive
            _LOGGER.debug("skipping malformed summary record for %s", device_id)
            continue

        sub_mode = mode_index % MODE_BANK_SIZE
        bank = mode_index // MODE_BANK_SIZE
        mode_key = SUB_MODE_MAP.get(sub_mode, "unknown")
        detail = SUB_MODE_DETAIL.get(sub_mode, f"unknown_{sub_mode}")
        available = mode_key != "offline"

        states[device_id] = ThermostatState(
            device_id=device_id,
            name=names.get(device_id, f"Zone {device_id}"),
            status_flag=status_flag,
            mode_index=mode_index,
            # An offline node reports the 6.5 C sentinel for both readings.
            # Reporting that as a real measurement would look like a frozen room.
            current_temperature=None
            if not available and current == OFFLINE_TEMP_SENTINEL
            else current,
            target_temperature=None
            if not available and target == OFFLINE_TEMP_SENTINEL
            else target,
            available=available,
            mode_key=mode_key,
            detail=detail,
            preset=MODE_KEY_TO_PRESET.get(mode_key),
            heat_demand=bool(bank) if available else None,
        )
    return states


def build_snapshot(device_id: str, attributes: dict[str, Attribute]) -> GatewaySnapshot:
    """Assemble a poll result from a decoded attribute table."""

    def val(name: str) -> str:
        attr = attributes.get(name)
        return attr.value if attr else ""

    names = parse_device_names(val(ATTR_NAMES_LOW), val(ATTR_NAMES_HIGH))
    thermostats = parse_summary(val(ATTR_SUMMARY), names)

    # B07 is 'Set HW Boost Hours' -- an outbound command, not a device list. The
    # presence of a hot water circuit is indicated by S07, and absent that there
    # is nothing to expose. The upstream integration reads B07 as an id and
    # fabricates a switch from the first thermostat's bytes when it is empty.
    has_hot_water = bool(val(ATTR_HW_DEVICE_SETTING).strip())

    error_message = val("S09").strip()

    return GatewaySnapshot(
        device_id=device_id,
        online=val(ATTR_ONLINE).strip().lower() == "true",
        group_name=(val("S04").strip().split("  ")[0] or None),
        it600_version=val("005").strip() or None,
        gateway_version=val("006").strip() or None,
        serial=val("007").strip() or None,
        error_message=None if error_message in ("", "{}") else error_message,
        has_hot_water=has_hot_water,
        thermostats=thermostats,
        raw_attributes=attributes,
    )


def encode_setpoint(device_id: str, temperature: float) -> str:
    """Build a B06 payload. Verified against the gateway's retained last write."""
    if not MIN_TEMP <= temperature <= MAX_TEMP:
        raise ValueError(f"setpoint {temperature} outside {MIN_TEMP}-{MAX_TEMP}")
    steps = round(temperature / TEMP_STEP)
    return f"{WRITE_PREFIX}{device_id}{chr(steps + CHAR_OFFSET)}"


def encode_mode(device_id: str, mode_index: int) -> str:
    """Build a B05 payload.

    PROVISIONAL. The encoding matches the summary's own offset-by-32 scheme and
    the gateway's retained last write, but which index means "resume schedule"
    has not been established, so nothing calls this yet.
    """
    if not 0 <= mode_index <= 25:
        raise ValueError(f"mode index {mode_index} out of range")
    payload = f"{WRITE_PREFIX}{device_id}{chr(mode_index + CHAR_OFFSET)}"
    return payload.ljust(MODE_WRITE_WIDTH)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class JgAuraClient:
    """Talks to the Arrayent ZAMAPI endpoint the JG Aura app uses."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        email: str,
        password: str | None = None,
        password_hash: str | None = None,
    ) -> None:
        if not (password or password_hash):
            raise ValueError("one of password or password_hash is required")
        self._session = session
        self._host = host.rstrip("/")
        self._email = email
        self._password_hash = password_hash or hashlib.md5(
            password.encode()  # noqa: S324 - the API mandates MD5
        ).hexdigest()
        self._token: str | None = None
        self._user_id: str | None = None
        self._gateway_id: str | None = None
        self._lock = asyncio.Lock()

    @property
    def password_hash(self) -> str:
        return self._password_hash

    @property
    def gateway_id(self) -> str | None:
        return self._gateway_id

    @staticmethod
    def _timestamp() -> str:
        return str(datetime.now(timezone.utc).timestamp()).replace(".", "")

    async def _get(self, path: str, **params: Any) -> str:
        query = urllib.parse.urlencode({**params, "timestamp": self._timestamp()})
        url = f"{self._host}/{path}?{query}"
        try:
            async with self._session.get(
                url, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            ) as response:
                body = await response.text()
                if response.status in (401, 403):
                    raise JgAuraAuthError(f"{path} rejected the session")
                if response.status != 200:
                    raise JgAuraResponseError(f"{path} returned HTTP {response.status}")
                return body
        except asyncio.TimeoutError as err:
            raise JgAuraConnectionError(f"{path} timed out") from err
        except aiohttp.ClientError as err:
            raise JgAuraConnectionError(f"{path} failed: {_safe(str(err))}") from err

    async def login(self) -> None:
        """Authenticate and locate the gateway."""
        body = await self._get(
            "userLogin",
            appId=APP_ID,
            name=self._email,
            password=self._password_hash,
        )
        try:
            root = ET.fromstring(body)
        except ET.ParseError as err:
            raise JgAuraResponseError(f"login reply was not XML: {err}") from err

        token = root.findtext(".//securityToken")
        user_id = root.findtext(".//userId")
        if not token or not user_id:
            # The API answers 200 with an empty/error body for bad credentials.
            raise JgAuraAuthError("login did not return a session token")
        self._token, self._user_id = token, user_id
        _LOGGER.debug("authenticated as user %s", user_id)

        body = await self._get("getDeviceList", secToken=token, userId=user_id)
        try:
            root = ET.fromstring(body)
        except ET.ParseError as err:
            raise JgAuraResponseError(f"device list was not XML: {err}") from err
        ids = [e.text for e in root.iter() if _local(e.tag) == "devId" and e.text]
        if not ids:
            raise JgAuraResponseError("account has no gateway registered")
        self._gateway_id = ids[0]
        if len(ids) > 1:
            _LOGGER.warning(
                "account lists %d gateways; using %s", len(ids), self._gateway_id
            )

    async def _ensure_session(self) -> None:
        if not (self._token and self._gateway_id):
            await self.login()

    async def async_get_snapshot(self) -> GatewaySnapshot:
        """Poll the gateway. Re-authenticates once if the session has expired.

        A reflush nudge is written first. This is NOT optional: the cloud holds
        a cached copy of the gateway's attributes and the gateway does not push
        updates on its own. Without the nudge the summary blob goes stale
        indefinitely -- observed 2026-08-05, when a thermostat changed at the
        wall and via the JG Aura app both continued to read as their previous
        values for over eight minutes, byte-for-byte identical across polls.
        """
        async with self._lock:
            await self._ensure_session()

            try:
                await self._write_attribute_locked(ATTR_REFLUSH, "1")
                await asyncio.sleep(REFLUSH_SETTLE)
            except JgAuraError as err:
                # Prefer stale data over no data -- but say so, because silently
                # serving a stale snapshot is exactly the trap this call avoids.
                _LOGGER.warning(
                    "reflush nudge failed (%s); this poll may return stale values",
                    err,
                )

            try:
                body = await self._read_attributes()
            except (JgAuraAuthError, JgAuraResponseError):
                _LOGGER.debug("re-authenticating and retrying the poll")
                await self.login()
                body = await self._read_attributes()

            attributes = parse_attributes(body)
            assert self._gateway_id is not None
            return build_snapshot(self._gateway_id, attributes)

    async def _read_attributes(self) -> str:
        # deviceTypeId is ignored by the gateway -- 1 and 2 returned byte-identical
        # bodies -- but it is part of the call the app makes, so keep sending it.
        return await self._get(
            "getDeviceAttributesWithValues",
            secToken=self._token,
            devId=self._gateway_id,
            deviceTypeId=1,
        )

    async def _write_attribute_locked(self, name: str, value: str) -> None:
        """Write one attribute. Caller must already hold self._lock."""
        await self._ensure_session()
        body = await self._get(
            "setMultiDeviceAttributes2",
            secToken=self._token,
            devId=self._gateway_id,
            name1=name,
            value1=value,
        )
        try:
            root = ET.fromstring(body)
        except ET.ParseError as err:
            raise JgAuraResponseError(f"write reply was not XML: {err}") from err
        ret = root.findtext(".//retCode")
        if ret != "0":
            raise JgAuraResponseError(f"write to {name} returned retCode {ret}")

    async def _write_attribute(self, name: str, value: str) -> None:
        async with self._lock:
            await self._write_attribute_locked(name, value)

    async def async_set_temperature(self, device_id: str, temperature: float) -> None:
        """Set a zone's target temperature."""
        await self._write_attribute(ATTR_SET_SETPOINT, encode_setpoint(device_id, temperature))

    async def async_set_mode_index(self, device_id: str, mode_index: int) -> None:
        """Set a zone's operating mode. PROVISIONAL -- unverified, see encode_mode."""
        await self._write_attribute(ATTR_SET_MODE, encode_mode(device_id, mode_index))
