"""Constants and the JG Aura / Salus iT600 wire-format decode tables.

Everything here is derived from a live gateway's own self-describing attribute
table (JGHUB2 / SALJG30, typeName IT600_1, gateway fw 133913, IT600 fw 0176),
captured 2026-08-04, and extended on 2026-08-05 by exercising every mode from
the JG Aura app and reading back what the gateway retained. Each entry notes
whether it is verified or merely unobserved; nothing unobserved is writable.
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

# Settle time between writing the C10 reflush nudge and reading the attribute
# table back. Without the nudge the cloud serves an indefinitely stale cache;
# without the settle the read races the gateway's re-push.
REFLUSH_SETTLE: Final = 4.0

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
ATTR_REFLUSH: Final = "C10"          # "Reflush All Attributes" -- written before every poll
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
    1: "schedule",   # following schedule, at its High band
    2: "schedule",   # ... Medium band
    3: "schedule",   # ... Low band
    4: "high",       # verified: app writes 4 for High
    5: "high",       # observed on a zone set at the wall
    6: "low",        # verified: app writes 6 for Low
    7: "boost",      # verified: app writes 7 for Boost -- the legacy table calls
                     # this "High", which would mis-report a boosting zone
    8: "away",       # verified: app writes 8 for Away
    9: "frost",      # verified: observed on a zone set at the wall
    # 10 and 11 have never been observed. The legacy table calls them "ON"; that
    # is not evidence, so they get a detail label and no preset rather than a
    # guess that Home Assistant would display as fact.
    10: "on",
    11: "on",
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
    7: "boost",
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
#   B05 (mode)     : '!' + <4-char id> + chr(mode_index + 32) + <2-char parameter>
#
# Both are VERIFIED against the JG Aura app's own writes, and encode_setpoint /
# encode_mode reproduce them byte for byte.
#
# What a mode actually does on this system: it selects WHICH SETPOINT BAND from
# the schedule applies, rather than overriding the setpoint directly. Observed
# 2026-08-05 -- switching zone 80ec to High moved its target from 18.0 to 21.0.
# ---------------------------------------------------------------------------
WRITE_PREFIX: Final = "!"
MODE_WRITE_WIDTH: Final = 8

# The B05 payload carries a two-character PARAMETER after the mode character.
# It is a duration for the modes that take one and two spaces for those that do
# not — so MODE_WRITE_WIDTH is a field layout, not padding:
#
#   '!' + <4-char id> + chr(index + 32) + <2-char parameter>
#
# Every entry below was captured from the JG Aura app's own B05 write on
# 2026-08-05 and then confirmed against the index the gateway reported back:
#
#   Auto   -> !80ec"    index 2, no parameter
#   High   -> !80ec$    index 4, no parameter
#   Low    -> !80ec&    index 6, no parameter
#   Boost  -> !80ec'03  index 7, parameter = HOURS   (3 hours requested)
#   Away   -> !80ec(01  index 8, parameter = DAYS    (1 day requested)
#   Frost  -> index 9, seen on a zone set at the wall (no B05 write to observe)
#
# Note 7 is Boost, not the 10 the legacy table implies — and that table lists 7
# as "High", which would have mis-reported a boosting zone.
DEFAULT_BOOST_HOURS: Final = 1
DEFAULT_AWAY_DAYS: Final = 1

# preset -> (mode index, parameter or None)
MODE_WRITE_MAP: Final[dict[str, tuple[int, int | None]]] = {
    PRESET_SCHEDULE: (2, None),
    PRESET_HIGH: (4, None),
    PRESET_LOW: (6, None),
    PRESET_BOOST: (7, DEFAULT_BOOST_HOURS),
    PRESET_AWAY: (8, DEFAULT_AWAY_DAYS),
    PRESET_FROST: (9, None),
}

# What each mode does to the target: a mode selects which setpoint band applies
# rather than overriding the setpoint. Observed on zone 80ec, whose schedule
# gave High/Boost 21.0, Low and the medium band 18.0, and Away/Frost 5.0.
# Recorded for reference only — the integration always reads the real value.

MIN_TEMP: Final = 5.0
MAX_TEMP: Final = 35.0
