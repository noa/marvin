"""Notification dispatchers and formatters for Always-On Marvin.

Supports native macOS desktop notifications (via osascript),
rich interactive terminal HUDs, and ambient statusline formatting.
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Literal

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from marvin import styles
from marvin.proactive_engine import ProactiveAlert


class MacOSNotifier:
    """Dispatches notifications via macOS osascript."""

    @staticmethod
    def is_available() -> bool:
        """Check if running on macOS with osascript available."""
        return platform.system() == "Darwin" and shutil.which("osascript") is not None

    @classmethod
    def send_notification(
        cls,
        title: str,
        message: str,
        subtitle: str = "Marvin Lab Agent",
        sound: str = "default",
    ) -> bool:
        """Send a standard banner notification to macOS Notification Center."""
        if not cls.is_available():
            return False

        # Escape quotes for AppleScript
        safe_title = title.replace('"', '\\"')
        safe_msg = message.replace('"', '\\"')
        safe_sub = subtitle.replace('"', '\\"')

        script = (
            f'display notification "{safe_msg}" '
            f'with title "{safe_title}" '
            f'subtitle "{safe_sub}" '
            f'sound name "{sound}"'
        )

        try:
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                check=True,
                text=True,
                timeout=5,
            )
            return True
        except Exception:
            return False

    @classmethod
    def send_interactive_dialog(
        cls,
        title: str,
        message: str,
        buttons: list[str] | None = None,
        default_button: str | None = None,
    ) -> str | None:
        """Send a macOS alert dialog with actionable buttons.

        Returns:
            The label of the button clicked by the user, or None if dismissed/error.
        """
        if not cls.is_available():
            return None

        btns = buttons or ["Snooze", "Open Marvin", "OK"]
        def_btn = default_button or btns[-1]

        btn_str = ", ".join(f'"{b.replace(chr(34), "")}"' for b in btns)
        safe_title = title.replace('"', '\\"')
        safe_msg = message.replace('"', '\\"')

        script = (
            f'display dialog "{safe_msg}" '
            f'with title "{safe_title}" '
            f'buttons {{{btn_str}}} '
            f'default button "{def_btn}"'
        )

        try:
            res = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                check=True,
                text=True,
                timeout=30,
            )
            out = res.stdout.strip()
            # output looks like: button returned:OK
            if "button returned:" in out:
                return out.split("button returned:", 1)[1].strip()
            return None
        except Exception:
            return None


class ConsoleHUDNotifier:
    """Renders proactive alerts into rich terminal panels and summaries."""

    def __init__(self, console: Console | None = None):
        self.console = console or styles.console

    def render_alerts(
        self,
        alerts: list[ProactiveAlert],
        title: str = "Marvin Proactive Triage",
    ) -> None:
        """Render a list of proactive alerts to the console."""
        if not alerts:
            self.console.print(
                Panel(
                    "[dim green]✓ No urgent items or blockers detected. All clear![/dim green]",
                    title="[bold green]Marvin Status[/bold green]",
                    border_style="green",
                )
            )
            return

        self.console.print(f"\n[bold magenta]⚡ {title}[/bold magenta] ({len(alerts)} items):\n")

        for i, alert in enumerate(alerts, 1):
            category_color = {
                "deadline": "bright_red",
                "subtask_bottleneck": "bright_magenta",
                "blocker": "yellow",
                "idea_decay": "cyan",
                "triage": "blue",
            }.get(alert.category, "white")

            category_icon = {
                "deadline": "⏳",
                "subtask_bottleneck": "⚠️",
                "blocker": "🛑",
                "idea_decay": "🌱",
                "triage": "✉" if alert.item_type == "email" else "📋",
            }.get(alert.category, "•")

            panel_title = f"[{category_color}]{category_icon} {alert.title} (Score: {alert.urgency_score:.0f})[/{category_color}]"

            body_lines = [f"[white]{alert.narrative}[/white]"]

            if alert.actions:
                body_lines.append("")
                body_lines.append("[dim]Suggested Actions:[/dim]")
                action_strs = []
                for act in alert.actions:
                    action_strs.append(f"[bold cyan][{act.label}][/bold cyan]")
                body_lines.append("  " + "  ".join(action_strs))

            self.console.print(
                Panel(
                    "\n".join(body_lines),
                    title=panel_title,
                    border_style=category_color,
                    padding=(0, 1),
                )
            )


class AmbientStatusFormatter:
    """Formats single-line summaries for shell prompt / status bar integration."""

    @staticmethod
    def format_status(
        due_today_count: int,
        overdue_count: int,
        blocker_count: int,
        expiring_ideas_count: int,
        untriaged_emails_count: int = 0,
        use_emojis: bool = True,
    ) -> str:
        """Format a single-line ambient status string."""
        parts = []

        if overdue_count > 0:
            icon = "🚨 " if use_emojis else ""
            parts.append(f"{icon}{overdue_count} overdue")

        if due_today_count > 0:
            icon = "⏳ " if use_emojis else ""
            parts.append(f"{icon}{due_today_count} due today")

        if blocker_count > 0:
            icon = "🛑 " if use_emojis else ""
            parts.append(f"{icon}{blocker_count} waiting")

        if expiring_ideas_count > 0:
            icon = "🌱 " if use_emojis else ""
            parts.append(f"{icon}{expiring_ideas_count} expiring ideas")

        if untriaged_emails_count > 0:
            icon = "✉ " if use_emojis else ""
            parts.append(f"{icon}{untriaged_emails_count} untriaged")

        if not parts:
            icon = "✓ " if use_emojis else ""
            return f"{icon}Marvin: all clear"

        return f"Marvin: " + " | ".join(parts)


class NotificationDispatcher:
    """Coordinates dispatching proactive alerts to enabled channels."""

    @classmethod
    def dispatch(
        cls,
        alerts: list[ProactiveAlert],
        channels: list[Literal["macos", "console"]] | None = None,
        data_dir: Path | None = None,
    ) -> dict[str, int]:
        """Dispatch alerts to specified channels and record in daemon state."""
        ch = channels or ["console", "macos"]
        stats = {"dispatched": 0, "macos": 0, "console": 0}

        if not alerts:
            return stats

        # Console output
        if "console" in ch:
            notifier = ConsoleHUDNotifier()
            notifier.render_alerts(alerts)
            stats["console"] = len(alerts)

        # macOS desktop notifications
        if "macos" in ch and MacOSNotifier.is_available():
            # Send top alert or summary
            top_alert = alerts[0]
            if len(alerts) == 1:
                title = f"Marvin: {top_alert.title}"
                msg = top_alert.narrative
            else:
                title = f"Marvin: {len(alerts)} Proactive Alerts"
                msg = f"{top_alert.title} (+{len(alerts) - 1} more items)"

            sent = MacOSNotifier.send_notification(title=title, message=msg)
            if sent:
                stats["macos"] += 1

        stats["dispatched"] = len(alerts)
        return stats
