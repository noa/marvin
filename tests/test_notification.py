"""Tests for notification.py (Dispatchers, console HUD, and ambient statusline)."""

from datetime import datetime
from unittest.mock import MagicMock, patch

from rich.console import Console

from marvin.notification import (
    AmbientStatusFormatter,
    ConsoleHUDNotifier,
    MacOSNotifier,
    NotificationDispatcher,
)
from marvin.proactive_engine import ProactiveAction, ProactiveAlert


def test_ambient_status_formatting():
    """Test single-line ambient status formatting."""
    # All clear
    clear_msg = AmbientStatusFormatter.format_status(
        due_today_count=0,
        overdue_count=0,
        blocker_count=0,
        expiring_ideas_count=0,
        use_emojis=True,
    )
    assert "all clear" in clear_msg
    assert "✓" in clear_msg

    # Active items with untriaged emails
    status_msg = AmbientStatusFormatter.format_status(
        due_today_count=2,
        overdue_count=1,
        blocker_count=3,
        expiring_ideas_count=1,
        untriaged_emails_count=4,
        use_emojis=True,
    )
    assert "1 overdue" in status_msg
    assert "2 due today" in status_msg
    assert "3 waiting" in status_msg
    assert "1 expiring ideas" in status_msg
    assert "4 untriaged" in status_msg
    assert "✉" in status_msg

    # Without emojis
    no_emoji_msg = AmbientStatusFormatter.format_status(
        due_today_count=1,
        overdue_count=0,
        blocker_count=0,
        expiring_ideas_count=0,
        untriaged_emails_count=2,
        use_emojis=False,
    )
    assert "⏳" not in no_emoji_msg
    assert "✉" not in no_emoji_msg
    assert "1 due today" in no_emoji_msg
    assert "2 untriaged" in no_emoji_msg


def test_console_hud_notifier_rendering():
    """Test ConsoleHUDNotifier renders without error."""
    console = Console(record=True, width=80)
    notifier = ConsoleHUDNotifier(console=console)

    # Render empty list
    notifier.render_alerts([], title="Test Status")
    output_empty = console.export_text()
    assert "All clear" in output_empty

    # Render alert with actions
    alert = ProactiveAlert(
        id="alert_test",
        item_id="t123",
        item_type="task",
        title="Due TODAY: Submit Report",
        narrative="The annual NSF report is due before 5pm.",
        urgency_tier="t_minus_24h",
        urgency_score=95.0,
        category="deadline",
        actions=[
            ProactiveAction(label="Mark Done", action_type="done"),
            ProactiveAction(label="Snooze 24h", action_type="snooze"),
        ],
        created_at=datetime.now(),
    )

    console = Console(record=True, width=80)
    notifier = ConsoleHUDNotifier(console=console)
    notifier.render_alerts([alert], title="Proactive Triage")
    output_alert = console.export_text()
    assert "Submit Report" in output_alert
    assert "Mark Done" in output_alert
    assert "Snooze 24h" in output_alert


def test_macos_notifier_dispatch():
    """Test MacOSNotifier osascript execution."""
    with patch("platform.system", return_value="Darwin"), \
         patch("shutil.which", return_value="/usr/bin/osascript"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="button returned:OK\n")

        sent = MacOSNotifier.send_notification("Title", "Message")
        assert sent is True
        mock_run.assert_called_once()

        # Test interactive dialog
        clicked = MacOSNotifier.send_interactive_dialog("Title", "Message", buttons=["Snooze", "OK"])
        assert clicked == "OK"


def test_notification_dispatcher():
    """Test high-level dispatcher coordinator."""
    alert = ProactiveAlert(
        id="alert_1",
        item_id="task_1",
        item_type="task",
        title="Test Alert",
        narrative="Test narrative",
        urgency_tier="t_minus_24h",
        urgency_score=80.0,
        category="deadline",
        actions=[],
        created_at=datetime.now(),
    )

    with patch.object(MacOSNotifier, "is_available", return_value=True), \
         patch.object(MacOSNotifier, "send_notification", return_value=True), \
         patch.object(ConsoleHUDNotifier, "render_alerts") as mock_render:

        stats = NotificationDispatcher.dispatch([alert], channels=["console", "macos"])
        assert stats["dispatched"] == 1
        assert stats["macos"] == 1
        assert stats["console"] == 1
        mock_render.assert_called_once()
