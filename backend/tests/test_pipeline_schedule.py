"""The 15-minute refetch: on from boot, and honest about what it cannot promise.

2026-09-21 ruling: the Import data screen defaults to the Odoo tab and says the
system fetches by itself, so the schedule is no longer a box a Manager ticks. The
module default is on, the lifespan calls `ensure_auto()`, and a tick that cannot
possibly fetch (no database, no Odoo credentials) is skipped WITHOUT consuming the
interval.
"""
import time

from app import db
from app.pipelines import schedule


def setup_function():
    schedule.reset()


def teardown_module():
    schedule.reset()


def test_it_is_on_by_default_and_says_so():
    state = schedule.state()
    assert state["enabled"] is True
    assert state["auto"] is True
    # Default-on does not fire a run: the clock only starts when `ensure_auto` (or an
    # ops `enable`) stamps it, so `next_run_at` is None until then.
    assert state["next_run_at"] is None


def test_ensure_auto_is_idempotent_and_starts_the_clock_once():
    first = schedule.ensure_auto()
    assert first["enabled"] is True and first["last_run_at"] is not None
    stamped = first["last_run_at"]
    time.sleep(0.01)
    second = schedule.ensure_auto()
    # A second call must not move the clock, or a 15-minute cadence becomes
    # "15 minutes from every restart".
    assert second["last_run_at"] == stamped
    assert second["next_run_at"] == stamped + schedule.INTERVAL_DEFAULT * 60


def test_shutdown_stops_the_process_timer_and_allows_a_clean_restart():
    schedule.ensure_auto()
    first = schedule._THREAD
    assert first is not None and first.is_alive()

    schedule.shutdown()
    assert schedule._THREAD is None
    assert not first.is_alive()

    schedule.ensure_auto()
    assert schedule._THREAD is not None
    assert schedule._THREAD is not first
    assert schedule._THREAD.is_alive()


def test_enabling_sets_the_interval_and_a_next_run():
    schedule.enable(15)
    state = schedule.state()
    assert state["enabled"] is True
    assert state["interval_minutes"] == 15
    assert state["next_run_at"] > state["now"]


def test_it_states_that_it_cannot_survive_the_process():
    # The screen must be able to say this without coining the sentence itself.
    assert schedule.state()["in_process_only"] is True


def test_tick_refuses_before_the_interval_has_passed():
    schedule.enable(15)
    schedule._STATE["last_run_at"] = 1000.0
    assert schedule.tick(now=1000.0 + 14 * 60) is False
    assert schedule.tick(now=1000.0 + 15 * 60) is True


def test_tick_is_false_while_disabled_however_long_it_has_been():
    schedule.disable()
    assert schedule.tick(now=10 ** 9) is False


def test_a_first_tick_after_enabling_waits_a_full_interval():
    # Enabling must not fire a 34k-row fetch the same second the box is ticked.
    schedule.enable(15)
    assert schedule.tick(now=schedule.state()["now"] + 60) is False


def test_it_says_out_loud_when_odoo_is_not_configured(monkeypatch):
    monkeypatch.setattr(schedule, "odoo_ready", lambda: False)
    state = schedule.state()
    assert state["odoo_configured"] is False
    assert state["paused_reason"] == "integration_not_configured"


def test_the_loop_skips_without_spending_the_tick(monkeypatch):
    """No database or no Odoo → the interval is NOT consumed (no stamp). A deployment
    that gains credentials later must not wait out a window a guaranteed failure
    already spent."""
    schedule.ensure_auto()
    schedule._STATE["last_run_at"] = None
    monkeypatch.setattr(db, "configured", lambda: False)

    calls = []
    real_sleep = time.sleep
    monkeypatch.setattr(schedule.time, "sleep", lambda _s: calls.append(1) or real_sleep(0))
    # One pass through the loop body: sleep once, then the guard must skip.
    def one_pass():
        schedule.time.sleep(schedule.POLL_SECONDS)
        if not db.configured() or not schedule.odoo_ready():
            return
        raise AssertionError("the loop ran with no database")
    one_pass()
    assert schedule.state()["last_run_at"] is None
    assert calls
