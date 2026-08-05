# JG Aura for Home Assistant

Home Assistant integration for **JG Aura** underfloor heating (John Guest / RWC) —
the rebadged Salus iT600 system whose hub is a Salus **G30** (`SALJG30`, sold as
`JGHUB2`).

Built for Home Assistant **2026.7+**. Cloud-polling, via the Arrayent ZAMAPI
endpoint the JG Aura app itself uses.

## Why this exists

The popular `homeassistant_salus` / `pyit600` integrations talk to a **local HTTP
API on port 80** that only exists on UG600/UGE600/UG800 gateways. A JG Aura hub is
the earlier G30 generation: it has no local API (port 80 refuses connections) and no
EUID printed on its label, so those integrations can never be configured against it —
whatever you type in the IP/EUID form.

This integration goes via the cloud instead, which is the only route a G30 offers.

It is a rewrite of [`ek5932/jg_aura_ha`](https://github.com/ek5932/jg_aura_ha),
which no longer loads on current Home Assistant. Beyond the API modernisation, the
substantive fixes are:

| Issue | Upstream | Here |
|---|---|---|
| **Crashes on real systems** (its issue #1) | Iterates the *name* list and indexes into the summary. Gateways keep name entries for long-removed thermostats, so `[0]` on an empty filter raises `IndexError`. On the reference gateway, 8 of 17 names have no device — it fails on the first one. | Iterates the **summary** (the live, authoritative list); names are a lookup with an id fallback. |
| **Hardcoded attribute ids** | `2257`, `2287`, `2272` — per-tenant internal keys that differ between gateways. | Resolves by the `name` the gateway publishes for every attribute (`001`, `S02`, `B05` …). |
| **Request volume** | Two coordinators, two clients, 2 s and 5 s intervals, two requests per poll — roughly 50 req/min. | One client, one coordinator, one request per poll, 60 s default (30–600 configurable). |
| **Credential leak** | Logs the full request URL on failure — which carries the MD5 password hash *and* the session token. | Never logs a URL; token-shaped strings are scrubbed from logs and exception messages. |
| **Writes a setting every poll** | Sends `B01=5` before each read, believing it a cache refresh. `B01` is **"Hyper Duration"** — a boost parameter. | Writes nothing to poll. The real refresh attribute is `C10` "Reflush All Attributes". |
| **Phantom hot water switch** | Reads `B07` ("Set HW Boost Hours", an outbound command) as a device id; when empty its `'' in record` test matches the first zone and invents a switch from its bytes. | Detects hot water from `S07`, and creates nothing when there is none. |
| **Offline stats look live** | `mode_index > 9` counts as "on", but index 15 means OFFLINE. | Offline zones are `unavailable`, and the 6.5 °C offline sentinel is suppressed rather than reported as a freezing room. |
| **Invalid presets** | Read-back table yields `AUTO_MEDIUM`/`FROST`, which aren't in the declared `preset_modes` — Home Assistant raises. | One bidirectional map; scheduled levels collapse to a single preset with the detail kept as a state attribute. |
| Blocking `time.sleep()` in async paths; a new `aiohttp` session per request; YAML-only setup | | Non-blocking, HA's shared session, full config flow with reauth and reconfigure. |

## What you get

- A `climate` entity per live zone — current temperature, target, and `hvac_action`.
- Gateway diagnostic sensors: zone count, zones online, iT600 firmware, error message.
- Devices in the registry: each zone linked to the hub via `via_device`.
- A diagnostics download that includes the raw summary blob, so future decoding
  questions can be answered without re-running a probe.

Zone state attributes expose `jg_mode_index`, `jg_mode`, `jg_preset` and
`jg_status_flag` — deliberately, so the mode encoding can be confirmed from
recorder history.

## Status: setpoints yes, modes not yet

**Temperature writes are implemented.** The encoding is confirmed against the value
the gateway retained from the JG Aura app's own last write (`B06 = '!1898B'` →
`(66−32) × 0.5 = 17.0 °C`), and the unit tests assert it byte-for-byte.

**Mode/preset writes are deliberately disabled.** `ClimateEntityFeature.PRESET_MODE`
is not declared. The payload *format* is corroborated the same way
(`B05 = '!7e8f%  '`, where `ord('%') − 32 = 5`, the mode index that zone reports),
but *which index means "resume schedule"* is unknown, and guessing it on a live
heating system is not worth the risk. `encode_mode()` and
`async_set_mode_index()` exist and are tested; nothing calls them until the map is
established empirically.

Note the asymmetry to resolve when it is: mode writes appear space-padded to 8
characters, setpoint writes are not padded. That is a plausible cause of silent
write failures.

`hvac_action` reads the upper bank of the mode index (`index // 15`) as heat demand.
The arithmetic is tested; the *meaning* is inferred and wants confirming against a
zone that is actively calling for heat.

## Installation

Copy `custom_components/jg_aura/` into your Home Assistant `config/custom_components/`
directory and restart, or add this repository to HACS as a custom repository of type
*Integration*.

Then **Settings → Devices & Services → Add Integration → JG Aura**, and sign in with
the same account you use in the JG Aura app. Only the MD5 hash of the password is
stored — which is what the API accepts, so the plaintext is never persisted.

## Tests

```bash
python3 -m pytest
```

The suite runs without Home Assistant installed: `api.py` and `const.py` are
deliberately HA-free, and `tests/_loader.py` imports them directly. Every literal in
the tests is real captured gateway output, so they are genuine regression tests
rather than restatements of the implementation.

## Caveats

Cloud-dependent, and all JG Aura hardware is discontinued. The Arrayent platform is
still up as of August 2026 but has no SLA to you, and the JG Aura app itself is
poorly rated. For a fully local setup the only route is replacing the hub with a
genuine Salus UGE600/UG800 and using `homeassistant_salus` — first confirming with
Salus whether it will adopt the existing JG coordinator's ZigBee network.

## Credit

Protocol groundwork by [@ek5932](https://github.com/ek5932), whose `jg_client.py`
worked out the Arrayent call sequence and the offset-by-32 encoding.
