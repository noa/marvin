"""Daemon schema and state management for Always-On Marvin.

Defines Pydantic models for daemon_state.json, including quiet hours,
daily rate limits, snooze tracking, and notification cooldown history.
"""

from datetime import date, datetime, time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


def _parse_time_str(t_str: str) -> time:
    """Parse 'HH:MM' string to datetime.time."""
    parts = t_str.strip().split(":")
    return time(int(parts[0]), int(parts[1]))


class QuietHoursConfig(BaseModel):
    """Configuration for quiet hours suppression."""

    enabled: bool = True
    start: str = "22:00"  # HH:MM (24-hour)
    end: str = "07:30"    # HH:MM (24-hour)

    def is_quiet(self, check_dt: datetime | None = None) -> bool:
        """Check if check_dt (or now) falls inside quiet hours."""
        if not self.enabled:
            return False

        now = check_dt or datetime.now()
        current_time = now.time()

        start_time = _parse_time_str(self.start)
        end_time = _parse_time_str(self.end)

        if start_time <= end_time:
            # Simple daytime range, e.g., 01:00 to 06:00
            return start_time <= current_time <= end_time
        else:
            # Range crosses midnight, e.g., 22:00 to 07:30
            return current_time >= start_time or current_time <= end_time


class RateLimitConfig(BaseModel):
    """Rate-limiting and cooldown settings to prevent notification spam."""

    max_daily_pings: int = 3
    task_cooldown_hours: int = 48
    idea_cooldown_hours: int = 72
    collaborator_cooldown_hours: int = 48


class NotificationRecord(BaseModel):
    """Record of a sent notification."""

    item_id: str
    item_type: Literal["task", "idea", "collaborator", "general"]
    pinged_at: datetime
    urgency_tier: str
    reason: str


class SnoozeRecord(BaseModel):
    """Record of an active or past snooze for a specific item."""

    item_id: str
    snoozed_at: datetime = Field(default_factory=datetime.now)
    snoozed_until: datetime
    reason: str = ""

    def is_active(self, check_dt: datetime | None = None) -> bool:
        """Return True if snooze is currently in effect."""
        now = check_dt or datetime.now()
        return now < self.snoozed_until


class DaemonState(BaseModel):
    """Persistent state for Always-On Marvin."""

    version: str = "1.0"
    last_eval_timestamp: datetime | None = None
    notifications_sent_today: int = 0
    last_ping_date: date | None = None
    quiet_hours: QuietHoursConfig = Field(default_factory=QuietHoursConfig)
    rate_limits: RateLimitConfig = Field(default_factory=RateLimitConfig)
    history: list[NotificationRecord] = Field(default_factory=list)
    snoozes: dict[str, SnoozeRecord] = Field(default_factory=dict)

    def reset_daily_counter_if_needed(self, now_dt: datetime | None = None) -> None:
        """Reset the daily ping counter if date has advanced."""
        today = (now_dt or datetime.now()).date()
        if self.last_ping_date != today:
            self.notifications_sent_today = 0
            self.last_ping_date = today

    def get_active_snooze(
        self, item_id: str, now_dt: datetime | None = None
    ) -> SnoozeRecord | None:
        """Get the active snooze record for an item, or None."""
        clean_id = item_id.lower().strip()
        record = self.snoozes.get(clean_id)
        if record and record.is_active(now_dt):
            return record
        return None

    def snooze(
        self,
        item_id: str,
        until_dt: datetime,
        reason: str = "",
        now_dt: datetime | None = None,
    ) -> None:
        """Snooze alerts for a specific item until a specified datetime."""
        clean_id = item_id.lower().strip()
        self.snoozes[clean_id] = SnoozeRecord(
            item_id=clean_id,
            snoozed_at=now_dt or datetime.now(),
            snoozed_until=until_dt,
            reason=reason,
        )

    def unsnooze(self, item_id: str) -> bool:
        """Remove a snooze for an item. Returns True if was snoozed."""
        clean_id = item_id.lower().strip()
        if clean_id in self.snoozes:
            del self.snoozes[clean_id]
            return True
        return False

    def can_ping_item(
        self,
        item_id: str,
        item_type: Literal["task", "idea", "collaborator", "general"],
        urgency_tier: str,
        now_dt: datetime | None = None,
        bypass_rate_limit: bool = False,
    ) -> tuple[bool, str]:
        """Check if an item can be pinged based on quiet hours, rate limits, snoozes, and cooldowns.

        Returns:
            (can_ping, reason_if_blocked)
        """
        now = now_dt or datetime.now()

        # 1. Check quiet hours (unless critical urgency)
        is_critical = urgency_tier in ("t_minus_2h", "t_minus_24h", "urgent_deadline")
        if not is_critical and self.quiet_hours.is_quiet(now):
            return False, "quiet_hours"

        # 2. Check active snooze
        snooze = self.get_active_snooze(item_id, now)
        if snooze:
            return False, f"snoozed_until_{snooze.snoozed_until.isoformat()}"

        # 3. Check daily rate limit (unless critical or bypassed)
        self.reset_daily_counter_if_needed(now)
        if (
            not bypass_rate_limit
            and not is_critical
            and self.notifications_sent_today >= self.rate_limits.max_daily_pings
        ):
            return False, "daily_rate_limit_reached"

        # 4. Check per-item cooldown
        cooldown_hours = {
            "task": self.rate_limits.task_cooldown_hours,
            "idea": self.rate_limits.idea_cooldown_hours,
            "collaborator": self.rate_limits.collaborator_cooldown_hours,
            "general": 24,
        }.get(item_type, 48)

        clean_id = item_id.lower().strip()
        recent_pings = [
            h for h in self.history if h.item_id.lower().strip() == clean_id
        ]
        if recent_pings:
            last_ping = max(recent_pings, key=lambda x: x.pinged_at)
            hours_since = (now - last_ping.pinged_at).total_seconds() / 3600.0

            # If urgency has escalated to a higher tier, allow bypassing cooldown
            escalated = (
                urgency_tier != last_ping.urgency_tier
                and is_critical
            )
            if not escalated and hours_since < cooldown_hours:
                return False, f"cooldown_active_{hours_since:.1f}h_of_{cooldown_hours}h"

        return True, "ok"

    def record_notification(
        self,
        item_id: str,
        item_type: Literal["task", "idea", "collaborator", "general"],
        urgency_tier: str,
        reason: str,
        now_dt: datetime | None = None,
    ) -> None:
        """Record that a notification was sent."""
        now = now_dt or datetime.now()
        self.reset_daily_counter_if_needed(now)
        self.notifications_sent_today += 1
        self.last_ping_date = now.date()
        self.last_eval_timestamp = now

        self.history.append(
            NotificationRecord(
                item_id=item_id.lower().strip(),
                item_type=item_type,
                pinged_at=now,
                urgency_tier=urgency_tier,
                reason=reason,
            )
        )


def get_daemon_state_path(data_dir: Path) -> Path:
    """Return the path to daemon_state.json in data_dir."""
    return data_dir / "daemon_state.json"


def load_daemon_state(data_dir: Path) -> DaemonState:
    """Load daemon_state.json or return a fresh default state."""
    path = get_daemon_state_path(data_dir)
    if not path.exists():
        return DaemonState()
    try:
        content = path.read_text()
        if not content.strip():
            return DaemonState()
        return DaemonState.model_validate_json(content)
    except Exception:
        return DaemonState()


def save_daemon_state(state: DaemonState, data_dir: Path) -> None:
    """Save daemon_state.json to data_dir."""
    path = get_daemon_state_path(data_dir)
    path.write_text(state.model_dump_json(indent=2))
