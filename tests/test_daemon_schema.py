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


def test_daemon_state_prefix_snooze():
    """Test that 4-character prefix snoozes match full 6-character task IDs."""
    state = DaemonState()
    now = datetime(2026, 9, 1, 12, 0)
    state.quiet_hours.enabled = False

    # Snooze with 4-char prefix
    state.snooze("ae23", now + timedelta(days=2), reason="Blocked", now_dt=now)

    # Lookup with full ID
    snooze_rec = state.get_active_snooze("ae23f1", now)
    assert snooze_rec is not None
    assert snooze_rec.reason == "Blocked"

    # can_ping_item with full ID should be blocked
    can_ping, reason = state.can_ping_item("ae23f1", "task", "due_today", now_dt=now)
    assert can_ping is False
    assert "snoozed_until" in reason

    # Unsnooze with 4-char prefix
    assert state.unsnooze("ae23") is True
    assert state.get_active_snooze("ae23f1", now) is None


def test_daemon_state_critical_cooldown_escalation():
    """Test that due_today and overdue escalate and bypass cooldown."""
    state = DaemonState()
    state.quiet_hours.enabled = False
    state.rate_limits.task_cooldown_hours = 48
    now = datetime(2026, 9, 1, 10, 0)

    # 1. Ping due_tomorrow
    can_ping, _ = state.can_ping_item("task1", "task", "due_tomorrow", now_dt=now)
    assert can_ping is True
    state.record_notification("task1", "task", "due_tomorrow", "Due tomorrow", now_dt=now)

    # 2. Next morning (20h later), now due_today -> should escalate and bypass cooldown
    t_today = now + timedelta(hours=20)
    can_ping_today, _ = state.can_ping_item("task1", "task", "due_today", now_dt=t_today)
    assert can_ping_today is True
    state.record_notification("task1", "task", "due_today", "Due today", now_dt=t_today)

    # 3. Next day (24h later), now overdue -> should escalate and bypass cooldown
    t_overdue = t_today + timedelta(hours=24)
    can_ping_overdue, _ = state.can_ping_item("task1", "task", "overdue", now_dt=t_overdue)
    assert can_ping_overdue is True


def test_daemon_state_history_rotation():
    """Test that notification history is capped at MAX_HISTORY_ENTRIES."""
    state = DaemonState()
    now = datetime(2026, 9, 1, 10, 0)
    for i in range(120):
        state.record_notification(f"t_{i}", "task", "due_today", f"Task {i}", now_dt=now + timedelta(minutes=i))

    assert len(state.history) == 100
    assert state.history[0].item_id == "t_20"
    assert state.history[-1].item_id == "t_119"


def test_daemon_state_email_cooldown_and_untriaged_count(tmp_path: Path):
    """Test email-specific cooldown and untriaged email tracking."""
    state = DaemonState()
    state.quiet_hours.enabled = True
    state.quiet_hours.start = "22:00"
    state.quiet_hours.end = "07:30"
    state.rate_limits.email_cooldown_hours = 24
    state.untriaged_emails_count = 5
    now = datetime(2026, 9, 1, 14, 0)

    # 1. First email ping allowed
    can_ping, _ = state.can_ping_item("msg-101", "email", "urgent_email_action", now_dt=now)
    assert can_ping is True
    state.record_notification("msg-101", "email", "urgent_email_action", "Action needed", now_dt=now)

    # 2. Cooldown active 6 hours later
    t_later = now + timedelta(hours=6)
    can_ping2, reason2 = state.can_ping_item("msg-101", "email", "urgent_email_action", now_dt=t_later)
    assert can_ping2 is False
    assert "cooldown_active" in reason2

    # 3. Urgent blocker reply bypasses quiet hours
    t_night = datetime(2026, 9, 1, 23, 30)
    can_ping_crit, _ = state.can_ping_item("msg-102", "email", "urgent_blocker_reply", now_dt=t_night)
    assert can_ping_crit is True

    # 4. Serialization preserves untriaged_emails_count
    save_daemon_state(state, tmp_path)
    loaded = load_daemon_state(tmp_path)
    assert loaded.untriaged_emails_count == 5
    assert loaded.rate_limits.email_cooldown_hours == 24
