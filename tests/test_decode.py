"""Regression tests pinned to a real gateway capture.

Captured from a JGHUB2 (Salus SALJG30, typeName IT600_1, gateway firmware 133913,
iT600 firmware 0176) in August 2026. The encoded payloads -- the summary blob and
the retained command values -- are verbatim from the device. Zone names, the
gateway serial and the device id have been replaced with neutral placeholders;
the decoder treats names purely as a lookup table, so the tests are unaffected.

The two write-encoding tests are the strongest evidence here: they reproduce,
byte for byte, the payloads the JG Aura app itself last wrote and the gateway
retained.
"""

from __future__ import annotations

import pytest

from _loader import api, const

build_snapshot = api.build_snapshot
encode_mode = api.encode_mode
encode_setpoint = api.encode_setpoint
parse_attributes = api.parse_attributes
parse_device_names = api.parse_device_names
parse_summary = api.parse_summary

# --- captured values -------------------------------------------------------

SUMMARY = 'c9b0$#RD8848-/--1898$"RF7150$#RD7e8f$%UDd725$"TF80ec$#TDa64c$"UF725f$"THffff0000~'

NAMES_S02 = (
    "872aZone A,80b0Zone B,c4d0Zone C,7fc6Zone D,2417Zone E,7fd2Zone F,"
    "8ec1Zone G,3419Zone H,1898Zone H,7150Zone G,ad81Upper Landing,"
    "725fZone A (8),7e8fZone C,d725Zone D,80ecZone E,c9b0Zone I,a64cZone B,"
)

GROUP_NAME = (
    "Home      Group1    Group2    Group3    Group4    Group5    Group6    "
    "Group7    Group8    Group9    Group10   Group11   Group12   Group13   "
    "Group14   Group15   Group16   Group17   Group18   "
)


def _attr(attr_id: str, name: str, display: str, value: str) -> str:
    return (
        "<attrList>"
        f"<id>{attr_id}</id><name>{name}</name><displayName>{display}</displayName>"
        "<device>true</device><presistent>true</presistent><ts>false</ts>"
        "<global>false</global><tsValueType>0</tsValueType>"
        "<hardwareIOType>Input</hardwareIOType><enumeratedAlias>0</enumeratedAlias>"
        f"<value>{value}</value><updTime>1785883233625</updTime>"
        "</attrList>"
    )


def _xml(**overrides: str) -> str:
    rows = {
        ("2257", "001", "Summary (A01 ~ A10)"): SUMMARY.replace('"', "&quot;"),
        ("2287", "S02", "Name (A01 ~ A15)"): NAMES_S02,
        ("2288", "S03", "Name (A16 ~ A30)"): "",
        ("2289", "S04", "GroupName"): GROUP_NAME,
        ("2264", "S07", "HotWaterDeviceSetting"): overrides.get("S07", ""),
        ("2265", "S09", "Error Message"): overrides.get("S09", "{}"),
        ("2262", "online", "online"): overrides.get("online", "true"),
        ("2247", "005", "IT600 Version"): "0176",
        ("2271", "006", "Gateway Version"): "133913",
        ("2270", "007", "Gateway SID_PW"): "SAH00000000_00",
        ("2294", "B05", "Set Operation Mode"): "!7e8f%  ",
        ("2273", "B06", "Set Current Setpoint"): "!1898B",
        ("2272", "B07", "Set HW Boost Hours"): "",
    }
    body = "".join(_attr(i, n, d, v) for (i, n, d), v in rows.items())
    return (
        '<ns1:getDeviceAttributesWithValuesResponse xmlns:ns1="http://arrayent.com/zamapi/">'
        "<typeId>378</typeId><typeName>IT600_1</typeName><presenceInfo>1</presenceInfo>"
        f"{body}</ns1:getDeviceAttributesWithValuesResponse>"
    )


# --- attribute table -------------------------------------------------------


def test_attributes_are_keyed_by_name_not_id():
    attrs = parse_attributes(_xml())
    assert attrs["001"].id == "2257"
    assert attrs["001"].display_name == "Summary (A01 ~ A10)"
    assert attrs["B06"].value == "!1898B"
    # The whole point: ids are incidental, names are the contract.
    assert set(attrs) >= {"001", "S02", "B05", "B06", "online"}


def test_namespaced_tags_are_handled():
    assert parse_attributes(_xml())["online"].value == "true"


def test_empty_table_is_an_error():
    with pytest.raises(Exception):
        parse_attributes("<response/>")


# --- names -----------------------------------------------------------------


def test_name_list_includes_stale_entries():
    names = parse_device_names(NAMES_S02, "")
    assert len(names) == 17
    assert names["725f"] == "Zone A (8)"
    assert names["a64c"] == "Zone B"
    # 8 of these 17 have no live device -- proof the name list must never drive
    # iteration (upstream issue #1).
    live = set(parse_summary(SUMMARY))
    assert len(set(names) - live) == 9


def test_names_with_spaces_survive():
    assert parse_device_names("ad81Upper Landing,")["ad81"] == "Upper Landing"


def test_short_tokens_ignored():
    assert parse_device_names("abc,1234,") == {}


# --- summary ---------------------------------------------------------------


def test_summary_yields_nine_zones_and_stops_at_terminator():
    states = parse_summary(SUMMARY, parse_device_names(NAMES_S02))
    assert len(states) == 9
    assert "ffff" not in states


@pytest.mark.parametrize(
    ("device_id", "name", "current", "target", "mode_index"),
    [
        ("7150", "Zone G", 25.0, 18.0, 3),
        ("c9b0", "Zone I", 25.0, 18.0, 3),
        ("1898", "Zone H", 25.0, 19.0, 2),
        ("725f", "Zone A (8)", 26.0, 20.0, 2),
        ("80ec", "Zone E", 26.0, 18.0, 3),
        ("a64c", "Zone B", 26.5, 19.0, 2),
        ("7e8f", "Zone C", 26.5, 18.0, 5),
        ("d725", "Zone D", 26.0, 19.0, 2),
    ],
)
def test_live_zone_decode(device_id, name, current, target, mode_index):
    state = parse_summary(SUMMARY, parse_device_names(NAMES_S02))[device_id]
    assert state.name == name
    assert state.current_temperature == current
    assert state.target_temperature == target
    assert state.mode_index == mode_index
    assert state.available is True
    assert state.status_flag == 4


def test_offline_node_is_unavailable_and_suppresses_sentinel_temps():
    state = parse_summary(SUMMARY, parse_device_names(NAMES_S02))["8848"]
    assert state.available is False
    assert state.mode_index == 15
    assert state.mode_key == "offline"
    # 6.5 C on both readings is the offline sentinel, not a freezing room.
    assert state.current_temperature is None
    assert state.target_temperature is None
    assert state.heat_demand is None
    # No name in S02 -- must fall back, not crash.
    assert state.name == "Zone 8848"


def test_presets_are_always_within_the_declared_list():
    PRESET_MODES = const.PRESET_MODES

    for state in parse_summary(SUMMARY, parse_device_names(NAMES_S02)).values():
        assert state.preset is None or state.preset in PRESET_MODES


def test_scheduled_modes_collapse_to_one_preset_but_keep_detail():
    states = parse_summary(SUMMARY, parse_device_names(NAMES_S02))
    assert states["1898"].preset == "Follow Schedule"  # index 2 = AUTO_MEDIUM
    assert states["1898"].detail == "schedule_medium"
    assert states["7150"].detail == "schedule_low"  # index 3
    assert states["7e8f"].preset == "High"  # index 5


def test_partial_trailing_record_ignored():
    assert parse_summary("c9b0$#RD~") == parse_summary("c9b0$#RD")


def test_empty_summary_is_empty_not_an_error():
    assert parse_summary("") == {}


def test_heat_demand_reads_the_upper_bank():
    # PROVISIONAL semantics, but the arithmetic must be right: index 17 is
    # bank 1 / sub 2, i.e. the same mode as index 2 with the flag set.
    low = parse_summary("aaaa" + chr(36) + chr(34) + "RD")["aaaa"]
    high = parse_summary("aaaa" + chr(36) + chr(49) + "RD")["aaaa"]
    assert (low.mode_index, low.heat_demand) == (2, False)
    assert (high.mode_index, high.heat_demand) == (17, True)
    assert low.mode_key == high.mode_key == "schedule"


# --- snapshot --------------------------------------------------------------


def test_snapshot_metadata():
    snap = build_snapshot("100000000", parse_attributes(_xml()))
    assert snap.online is True
    assert snap.group_name == "Home"
    assert snap.it600_version == "0176"
    assert snap.gateway_version == "133913"
    assert snap.serial == "SAH00000000_00"
    assert snap.error_message is None  # '{}' means clean
    assert len(snap.thermostats) == 9


def test_no_hot_water_switch_is_invented():
    # B07 empty and S07 empty -> this system has no hot water circuit. Upstream
    # reads B07 as a device id and fabricates a switch from the first zone's bytes.
    snap = build_snapshot("100000000", parse_attributes(_xml()))
    assert snap.has_hot_water is False


def test_hot_water_detected_when_actually_present():
    snap = build_snapshot("100000000", parse_attributes(_xml(S07="2569Q")))
    assert snap.has_hot_water is True


def test_error_message_surfaced_when_non_empty():
    snap = build_snapshot("100000000", parse_attributes(_xml(S09='{"e":"1"}')))
    assert snap.error_message == '{"e":"1"}'


def test_offline_gateway():
    assert build_snapshot("1", parse_attributes(_xml(online="false"))).online is False


# --- write encoding: byte-exact against the gateway's retained writes ------


def test_setpoint_encoding_matches_the_gateways_retained_value():
    # The gateway still held B06 = '!1898B' from the JG Aura app's own last write.
    assert encode_setpoint("1898", 17.0) == "!1898B"


def test_mode_encoding_matches_the_gateways_retained_value():
    # B05 = '!7e8f%  ' -- 8 chars, space padded. Device 7e8f reports mode 5,
    # and ord('%') - 32 == 5, which is what confirms the offset-by-32 scheme.
    assert encode_mode("7e8f", 5) == "!7e8f%  "
    assert len(encode_mode("7e8f", 5)) == 8


@pytest.mark.parametrize(
    ("temp", "expected_char"),
    [(5.0, chr(42)), (17.0, "B"), (18.0, "D"), (19.0, "F"), (20.0, "H"), (26.5, "U")],
)
def test_setpoint_roundtrips_against_observed_summary_chars(temp, expected_char):
    assert encode_setpoint("abcd", temp) == f"!abcd{expected_char}"


def test_half_degrees_encode():
    assert encode_setpoint("abcd", 21.5) == "!abcd" + chr(43 + 32)


@pytest.mark.parametrize("temp", [4.5, 35.5, -10, 100])
def test_setpoint_out_of_range_rejected(temp):
    with pytest.raises(ValueError):
        encode_setpoint("abcd", temp)


@pytest.mark.parametrize("index", [-1, 26, 99])
def test_mode_index_out_of_range_rejected(index):
    with pytest.raises(ValueError):
        encode_mode("abcd", index)
