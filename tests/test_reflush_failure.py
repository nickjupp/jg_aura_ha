"""The reflush nudge must fail closed, not quietly serve a stale snapshot.

Regression cover for 8-11 September 2026, when the hub hung during a power cut
and the cloud went on serving its cached copy. Every zone reported byte-identical
values for 61 hours while the hub's LED, the `online` attribute and the
error-message sensor all read healthy -- all three downstream of the same cache.
The failing nudge was the only signal that knew, and it was logged and discarded.

These tests pin the three properties that fix depends on: that repeated failure
eventually raises, that a recovered nudge forgets the count, and that a single
blip still rides through.
"""

from __future__ import annotations

import asyncio

import pytest

from _loader import api, const

JgAuraError = api.JgAuraError
JgAuraStaleError = api.JgAuraStaleError
LIMIT = const.REFLUSH_FAILURE_LIMIT


class _Client(api.JgAuraClient):
    """A client with the network removed and the nudge under our control.

    Only `_write_attribute_locked` and `_read_attributes` are replaced, so the
    counter logic, the raise and the lock all run exactly as they do live.
    """

    def __init__(self, nudge_results: list[bool]) -> None:
        super().__init__(
            session=None,  # never touched: both network calls are overridden
            host="https://example.invalid",
            email="someone@example.invalid",
            password_hash="0" * 32,
        )
        self._nudge_results = list(nudge_results)
        self._token = "token"
        self._gateway_id = "201328421"
        self.reads = 0

    async def _write_attribute_locked(self, name: str, value: str) -> None:
        if self._nudge_results and not self._nudge_results.pop(0):
            raise JgAuraError("setMultiDeviceAttributes2 returned HTTP 500")

    async def _read_attributes(self) -> str:
        self.reads += 1
        return "<unused/>"

    async def _ensure_session(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _no_settle(monkeypatch):
    """Drop the 4 s post-nudge settle so the suite stays instant.

    The real `asyncio.sleep` is captured first: patching the module attribute
    and then calling `asyncio.sleep` inside the replacement calls the
    replacement, which is an infinite recursion rather than a fast test.
    """
    real_sleep = asyncio.sleep
    monkeypatch.setattr(api.asyncio, "sleep", lambda _delay: real_sleep(0))


def _snapshot_calls(client: _Client, count: int) -> list[BaseException | None]:
    """Poll `count` times, recording the exception from each (None if it passed)."""

    async def _run() -> list[BaseException | None]:
        out: list[BaseException | None] = []
        for _ in range(count):
            try:
                await client.async_get_snapshot()
                out.append(None)
            except BaseException as err:  # noqa: BLE001 - recording, not handling
                out.append(err)
        return out

    return asyncio.run(_run())


def test_the_limit_is_a_sane_policy():
    """Pin the policy, not just the plumbing.

    Every other test in this file derives its expectations from
    REFLUSH_FAILURE_LIMIT, so they stay green whatever it is set to -- proven
    by mutation on 12 Sep 2026, when raising it to 99 changed what they
    asserted instead of failing them. This is the assertion that bites.

    The bound is what makes the fix a fix. At the 60 s default poll a limit
    above five lets a dead gateway go unreported for more than five minutes,
    and the failure this exists to stop went unreported for 61 hours.
    """
    assert 2 <= LIMIT <= 5, "one failure is a hair trigger; six is not a guard"
    assert LIMIT * const.DEFAULT_SCAN_INTERVAL <= 300, (
        "worst-case staleness before the zones go unavailable must stay under "
        "five minutes at the default poll interval"
    )


def test_below_the_limit_still_serves_data(monkeypatch):
    """LIMIT-1 consecutive failures must not break the integration.

    A cloud blip is common and a dead hub is not; tolerating the former is the
    entire reason this is a counter rather than a hair trigger.
    """
    monkeypatch.setattr(api, "build_snapshot", lambda *a, **k: "snapshot")
    monkeypatch.setattr(api, "parse_attributes", lambda body: {})
    client = _Client([False] * (LIMIT - 1))

    results = _snapshot_calls(client, LIMIT - 1)

    assert results == [None] * (LIMIT - 1)
    assert client.reads == LIMIT - 1, "a tolerated failure must still read"
    assert client.reflush_failures == LIMIT - 1
    assert client.reflush_failing is True, "the sensor leads the unavailability"


def test_the_limit_raises_rather_than_serving_stale(monkeypatch):
    """The LIMIT-th consecutive failure must raise, and must not read."""
    monkeypatch.setattr(api, "build_snapshot", lambda *a, **k: "snapshot")
    monkeypatch.setattr(api, "parse_attributes", lambda body: {})
    client = _Client([False] * LIMIT)

    results = _snapshot_calls(client, LIMIT)

    assert results[:-1] == [None] * (LIMIT - 1)
    assert isinstance(results[-1], JgAuraStaleError)
    assert isinstance(results[-1], JgAuraError), "coordinator maps this to UpdateFailed"
    assert client.reads == LIMIT - 1, (
        "the failing poll must not fall through to a read -- fetching the cache "
        "anyway is the 61-hour bug"
    )


def test_recovery_forgets_the_count(monkeypatch):
    """A successful nudge resets the counter, so failures must be consecutive.

    Without this, isolated blips accumulate over days and the integration goes
    unavailable for reasons long since passed.
    """
    monkeypatch.setattr(api, "build_snapshot", lambda *a, **k: "snapshot")
    monkeypatch.setattr(api, "parse_attributes", lambda body: {})
    client = _Client([False] * (LIMIT - 1) + [True] + [False] * (LIMIT - 1))

    results = _snapshot_calls(client, 2 * LIMIT - 1)

    assert all(r is None for r in results), "no raise: the run never hits the limit"
    assert client.reflush_failures == LIMIT - 1
