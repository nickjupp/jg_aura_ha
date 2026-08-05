"""Constants and the JG Aura / Salus iT600 wire-format decode tables.

Everything here is derived from a live gateway's own self-describing attribute
table (JGHUB2 / SALJG30, typeName IT600_1, gateway fw 133913, IT600 fw 0176),
captured 2026-08-04. Where a value is inferred rather than observed it is
marked PROVISIONAL and must not be relied on for writes.
"""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "jg_aura"

DEFAULT_HOST: Final = "https://emea-salprod02-api.arrayent.com:8081/zdk/services/zamapi"
APP_ID: Final = "1097"

CONF_HOST: Final = "host"
CONF_SCAN_INTERVAL: Final = "scan_interval"

DEFAULT_SCAN_INTERVAL: Final = 60
MIN_SCAN_INTERVAL: Final = 30
MAX_SCAN_INTERVAL: Final = 600

# Delay after a write before asking the cloud for fresh state. The gateway is
# polled by the cloud rather than pushed to, so an immediate re-read returns the
# pre-write value.
POST_WRITE_REFRESH_DELAY: Final = 6.0

# ---------------------------------------------------------------------------
# Attribute NAMES.
#
# The gateway returns a `name` for every attribute alongside a numeric `id`.
# The ids are per-tenant internal keys and differ between gateways -- keying off
# them is the root cause of the upstream integration's issue #1. Always resolve
# by name.
# ---------------------------------------------------------------------------
ATTR_SUMMARY: Final = "001"          # "Summary (A01 ~ A10)"  -- live device state
ATTR_NAMES_LOW: Final = "S02"        # "Name (A01 ~ A15)"
ATTR_NAMES_HIGH: Final = "S03"       # "Name (A16 ~ A30)"
ATTR_DISPLAY_LOCATION: Final = "S01" # "Display Location (A01 ~ A30)"
ATTR_GROUP_NAME: Final = "S04"       # "GroupName"
ATTR_HW_DEVICE_SETTING: Final = "S07"  # "HotWaterDeviceSetting"
ATTR_ERROR_MESSAGE: Final = "S09"    # "Error Message"
ATTR_SET_MODE: Final = "B05"         # "Set Operation Mode"
ATTR_SET_SETPOINT: Final = "B06"     # "Set Current Setpoint"
ATTR_HW_BOOST_HOURS: Final = "B07"   # "Set HW Boost Hours"
ATTR_HYPER_DURATION: Final = "B01"   # "Hyper Duration" -- NOT a refresh. Do not write.
ATTR_REFLUSH: Final = "C10"          # "Reflush All Attributes"
ATTR_ONLINE: Final = "online"
ATTR_IT600_VERSION: Final = "005"    # "IT600 Version"
ATTR_GATEWAY_VERSION: Final = "006"  # "Gateway Version"
ATTR_GATEWAY_SID_PW: Final = "007"   # "Gateway SID_PW" -- matches the case label

# ---------------------------------------------------------------------------
# Summary blob encoding.
#
#   record = 4-char device id + 4-char state, repeated, terminated by 'ffff0000'
#   state[0] = status/flags byte   (observed 4 on live devices, 13 on a dead one)
#   state[1] = mode index
#   state[2] = current temperature
#   state[3] = target setpoint
#
# All numeric fields are ASCII offset by 32; temperatures are in 0.5 degree
# units, so degrees = (ord(c) - 32) * 0.5.
# ---------------------------------------------------------------------------
CHAR_OFFSET: Final = 32
TEMP_STEP: Final = 0.5
SUMMARY_RECORD_LEN: Final = 8
SUMMARY_ID_LEN: Final = 4
SUMMARY_TERMINATOR: Final = "ffff"

# Sentinel temperature reported by an offline node (6.5 C). Suppressed rather
# than shown, so a flat battery does not look like a freezing room.
OFFLINE_TEMP_SENTINEL: Final = 6.5

# The mode index is two banks of 15: `index % 15` selects the mode, and
# `index // 15` is the heat-demand flag.
#
# VERIFIED on live hardware 2026-08-05. Driving one zone (80ec) to 28.0 C
# against a 24.5 C room moved its reported index from 2 to 18 at the moment it
# began calling for heat; restoring 18.0 C returned it to 2. 18 // 15 == 1,
# 18 % 15 == 3 — so the bank bit flipped while the sub-mode stayed within the
# scheduled range. See test_heat_demand_verified_against_live_hardware.
MODE_BANK_SIZE: Final = 15

# Sub-mode (index % 15) -> canonical mode key.
SUB_MODE_MAP: Final[dict[int, str]] = {
    0: "offline",
    1: "schedule",   # AUTO_HIGH   -- following schedule, at its High level
    2: "schedule",   # AUTO_MEDIUM
    3: "schedule",   # AUTO_LOW
    4: "high",
    5: "high",
    6: "low",
    7: "high",
    8: "away",
    9: "frost",
    10: "boost",
    11: "boost",
}

# Finer-grained label for the scheduled levels, surfaced as a state attribute so
# the schedule level is not lost when collapsing to a preset.
SUB_MODE_DETAIL: Final[dict[int, str]] = {
    0: "offline",
    1: "schedule_high",
    2: "schedule_medium",
    3: "schedule_low",
    4: "manual_high",
    5: "manual_high",
    6: "manual_low",
    7: "manual_high",
    8: "away",
    9: "frost",
    10: "on",
    11: "on",
}

PRESET_SCHEDULE: Final = "Follow Schedule"
PRESET_HIGH: Final = "High"
PRESET_LOW: Final = "Low"
PRESET_AWAY: Final = "Away"
PRESET_FROST: Final = "Frost"
PRESET_BOOST: Final = "Boost"

MODE_KEY_TO_PRESET: Final[dict[str, str]] = {
    "schedule": PRESET_SCHEDULE,
    "high": PRESET_HIGH,
    "low": PRESET_LOW,
    "away": PRESET_AWAY,
    "frost": PRESET_FROST,
    "boost": PRESET_BOOST,
}

# Every preset HA may be asked to display. Home Assistant raises if a reported
# preset is absent from this list, so it must be a superset of everything
# MODE_KEY_TO_PRESET can produce.
PRESET_MODES: Final[list[str]] = [
    PRESET_SCHEDULE,
    PRESET_HIGH,
    PRESET_LOW,
    PRESET_AWAY,
    PRESET_FROST,
    PRESET_BOOST,
]

# ---------------------------------------------------------------------------
# Writes.
#
# Both command attributes use the same offset-by-32 scheme as the summary:
#
#   B06 (setpoint) : '!' + <4-char id> + chr(round(degrees / 0.5) + 32)
#   B05 (mode)     : '!' + <4-char id> + chr(mode_index + 32), space-padded to 8
#
# Corroborated by the values the gateway retained from the JG Aura app's own
# last writes: B06 = '!1898B' -> (66-32)*0.5 = 17.0 C, and B05 = '!7e8f%  '
# -> ord('%')-32 = 5, which is the mode index device 7e8f currently reports.
#
# Setpoint writes are considered verified. Mode writes are NOT: which index
# means "return to schedule" is unknown, so preset writing stays disabled until
# phase 4 establishes the map empirically.
# ---------------------------------------------------------------------------
WRITE_PREFIX: Final = "!"
MODE_WRITE_WIDTH: Final = 8

MIN_TEMP: Final = 5.0
MAX_TEMP: Final = 35.0
