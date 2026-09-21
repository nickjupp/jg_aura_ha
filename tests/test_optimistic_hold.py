"""An optimistic value must survive the eager post-write refresh.

Regression cover for 21 September 2026. Setting a zone to Medium from a wall
panel showed Medium, bounced back to Frost about six seconds later, then
returned to Medium a poll afterwards. The cause was not the write: it was
`_handle_coordinator_update` clearing the optimistic value on ANY update,
including the `POST_WRITE_REFRESH_DELAY` refresh -- which, as const.py says
itself, usually still answers with the pre-write value because the cloud polls
the gateway rather than being pushed to.

The fix holds an optimistic value until the gateway CONFIRMS it or a deadline
of `OPTIMISTIC_HOLD_INTERVALS` poll intervals passes. These tests pin both
halves, because dropping the deadline would mask a write that silently failed
-- the property the original unconditional clear existed to protect.
"""

from __future__ import annotations

from _loader import const

HOLD = const.OPTIMISTIC_HOLD_INTERVALS


class _Zone:
    def __init__(self, preset: str, target: float) -> None:
        self.preset = preset
        self.target_temperature = target


class _Entity:
    """The optimistic-hold logic of JgAuraClimate, with HA removed.

    Mirrors climate.JgAuraClimate._handle_coordinator_update exactly. The real
    class cannot be built without a HA instance, so the branch under test is
    reproduced here; if that method changes, this must change with it.
    """

    def __init__(self, zone: _Zone, interval: float = 60.0) -> None:
        self.zone = zone
        self._interval = interval
        self._optimistic_target: float | None = None
        self._optimistic_preset: str | None = None
        self._optimistic_deadline = 0.0
        self._now = 1000.0

    def _start_optimistic_hold(self) -> None:
        self._optimistic_deadline = self._now + self._interval * HOLD

    def set_preset(self, preset: str) -> None:
        self._optimistic_preset = preset
        self._start_optimistic_hold()

    def set_target(self, target: float) -> None:
        self._optimistic_target = target
        self._start_optimistic_hold()

    def coordinator_update(self) -> None:
        zone = self.zone
        expired = self._now >= self._optimistic_deadline
        if self._optimistic_target is not None and (
            expired
            or (zone is not None and zone.target_temperature == self._optimistic_target)
        ):
            self._optimistic_target = None
        if self._optimistic_preset is not None and (
            expired or (zone is not None and zone.preset == self._optimistic_preset)
        ):
            self._optimistic_preset = None

    @property
    def preset_mode(self) -> str | None:
        if self._optimistic_preset is not None:
            return self._optimistic_preset
        return self.zone.preset if self.zone else None

    @property
    def target_temperature(self) -> float | None:
        if self._optimistic_target is not None:
            return self._optimistic_target
        return self.zone.target_temperature if self.zone else None


def test_stale_post_write_refresh_does_not_bounce_the_preset():
    """The 6 s refresh still reporting Frost must not un-set Medium."""
    zone = _Zone("Frost", 5.0)
    e = _Entity(zone)

    e.set_preset("Medium")
    assert e.preset_mode == "Medium"

    # POST_WRITE_REFRESH_DELAY fires; the gateway has not caught up.
    e._now += const.POST_WRITE_REFRESH_DELAY
    e.coordinator_update()
    assert e.preset_mode == "Medium", "bounced back to the pre-write value"


def test_optimistic_preset_clears_once_the_gateway_confirms():
    zone = _Zone("Frost", 5.0)
    e = _Entity(zone)
    e.set_preset("Medium")

    e._now += 60.0
    zone.preset = "Medium"  # gateway has caught up
    e.coordinator_update()

    assert e._optimistic_preset is None, "should defer to the real value once it agrees"
    assert e.preset_mode == "Medium"


def test_a_silently_failed_write_still_reverts_after_the_deadline():
    """The property the original unconditional clear protected."""
    zone = _Zone("Frost", 5.0)
    e = _Entity(zone)
    e.set_preset("Medium")

    e._now += 60.0 * HOLD + 1  # deadline passed, gateway never agreed
    e.coordinator_update()

    assert e._optimistic_preset is None
    assert e.preset_mode == "Frost", "a failed write must not be masked forever"


def test_target_temperature_holds_and_confirms_the_same_way():
    zone = _Zone("Frost", 5.0)
    e = _Entity(zone)

    e.set_target(18.0)
    e._now += const.POST_WRITE_REFRESH_DELAY
    e.coordinator_update()
    assert e.target_temperature == 18.0

    zone.target_temperature = 18.0
    e._now += 60.0
    e.coordinator_update()
    assert e._optimistic_target is None
    assert e.target_temperature == 18.0


def test_hold_is_longer_than_the_post_write_refresh():
    """The whole fix rests on this ordering."""
    assert 60.0 * HOLD > const.POST_WRITE_REFRESH_DELAY
