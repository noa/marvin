"""Tests for daemon_schema.py (Always-On Marvin state & squelch rules)."""

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest

from marvin.daemon_schema import (
    DaemonState,
    NotificationRecord,
    QuietHoursConfig,
    RateLimitConfig,
    SnoozeRecord,
    load_daemon_state,
    save_daemon_state,
)


def test_quiet_hours_overnight():
    """Test quiet hours configuration crossing midnight (e.g. 22:00 to 07:30)."""
    qh = QuietHoursConfig(enabled=True, start="22:00", end="07:30")

    # Late night (23:15) -> Quiet
    t_late = datetime(2026, 9, 1, 23, 15)
    assert qh.is_quiet(t_late) is True

    # Early morning (06:45) -> Quiet
    t_early = datetime(2026, 9, 2, 6, 45)
    assert qh.is_quiet(t_early) is True

    # Midday (14:30) -> Not quiet
    t_midday = datetime(2026, 9, 2, 14, 30)
    assert qh.is_quiet(t_midday) is False

    # Disabled
    qh.enabled = False
    assert qh.is_quiet(t_late) is False


def test_quiet_hours_daytime():
    """Test quiet hours within the same calendar day (e.g. 01:00 to 06:00)."""
    qh = QuietHoursConfig(enabled=True, start="01:00", end="06:00")

    assert qh.is_quiet(datetime(2026, 9, 1, 3, 0)) is True
    assert qh.is_quiet(datetime(2026, 9, 1, 12, 0)) is False


def test_snooze_record_expiration():
    """Test SnoozeRecord active check."""
    now = datetime(2026, 9, 1, 12, 0)
    future = now + timedelta(days=2)
    past = now - timedelta(days=1)

    active_snooze = SnoozeRecord(item_id="ae23", snoozed_until=future)
    assert active_snooze.is_active(now) is True

    expired_snooze = SnoozeRecord(item_id="ae23", snoozed_until=past)
    assert expired_snooze.is_active(now) is False


def test_daemon_state_snooze_and_unsnooze():
    """Test DaemonState snooze management."""
    state = DaemonState()
    now = datetime(2026, 9, 1, 10, 0)
    until = now + timedelta(days=1)

    state.snooze("ae23f1", until, reason="Waiting for student meeting", now_dt=now)
    assert state.get_active_snooze("ae23f1", now) is not None
    assert state.get_active_snooze("AE23F1", now) is not None  # Case insensitive

    # Check unsnooze
    assert state.unsnooze("ae23f1") is True
    assert state.get_active_snooze("ae23f1", now) is None
    assert state.unsnooze("ae23f1") is False


def test_daemon_state_can_ping_snooze_check():
    """Test that active snooze blocks pings."""
    state = DaemonState()
    now = datetime(2026, 9, 1, 14, 0)
    state.quiet_hours.enabled = False

    state.snooze("ae23", now + timedelta(hours=5), now_dt=now)

    can_ping, reason = state.can_ping_item("ae23", "task", "t_minus_3d", now_dt=now)
    assert can_ping is False
    assert "snoozed_until" in reason

    # Different item should not be blocked
    can_ping_other, _ = state.can_ping_item("other_task", "task", "t_minus_3d", now_dt=now)
    assert can_ping_other is True


def test_daemon_state_rate_limit_and_cooldown():
    """Test daily rate limits and per-item cooldowns."""
    state = DaemonState()
    state.quiet_hours.enabled = False
    state.rate_limits.max_daily_pings = 2
    state.rate_limits.task_cooldown_hours = 24

    now = datetime(2026, 9, 1, 10, 0)

    # First notification
    can_ping, _ = state.can_ping_item("task1", "task", "t_minus_7d", now_dt=now)
    assert can_ping is True
    state.record_notification("task1", "task", "t_minus_7d", "due in 7d", now_dt=now)
    assert state.notifications_sent_today == 1

    # Second notification on same task within cooldown
    can_ping_same, reason_same = state.can_ping_item("task1", "task", "t_minus_7d", now_dt=now + timedelta(hours=2))
    assert can_ping_same is False
    assert "cooldown_active" in reason_same

    # Second notification on different task
    can_ping_2, _ = state.can_ping_item("task2", "task", "t_minus_7d", now_dt=now + timedelta(hours=2))
    assert can_ping_2 is True
    state.record_notification("task2", "task", "t_minus_7d", "due in 7d", now_dt=now + timedelta(hours=2))
    assert state.notifications_sent_today == 2

    # Third notification should exceed daily limit
    can_ping_3, reason_3 = state.can_ping_item("task3", "task", "t_minus_7d", now_dt=now + timedelta(hours=3))
    assert can_ping_3 is False
    assert reason_3 == "daily_rate_limit_reached"

    # Critical urgency (t_minus_24h) bypasses daily rate limit
    can_ping_crit, _ = state.can_ping_item("task3", "task", "t_minus_24h", now_dt=now + timedelta(hours=3))
    assert can_ping_crit is True


def test_daemon_state_save_and_load(tmp_path: Path):
    """Test persistence of DaemonState."""
    state = DaemonState()
    state.rate_limits.max_daily_pings = 5
    now = datetime(2026, 9, 1, 12, 0)
    state.snooze("task1", now + timedelta(days=1), reason="Vacation", now_dt=now)
    state.record_notification("task2", "task", "overdue", "Late task", now_dt=now)

    save_daemon_state(state, tmp_path)

    loaded = load_daemon_state(tmp_path)
    assert loaded.rate_limits.max_daily_pings == 5
    assert len(loaded.history) == 1
    assert loaded.history[0].item_id == "task2"
    assert "task1" in loaded.snoozes
