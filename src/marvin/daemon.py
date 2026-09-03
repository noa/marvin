"""Daemon service runner and launchd manager for Always-On Marvin."""

import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Literal

from marvin import fast_path
from marvin.daemon_schema import (
    DaemonState,
    load_daemon_state,
    save_daemon_state,
)
from marvin.proactive_engine import ProactiveAlert, evaluate_knowledge_state
from marvin.notification import (
    AmbientStatusFormatter,
    NotificationDispatcher,
)


LAUNCHD_LABEL = "com.noa.marvin.daemon"


class MarvinDaemon:
    """Always-On Marvin daemon service."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def run_once(
        self,
        notify: bool = True,
        dry_run: bool = False,
        bypass_filters: bool = False,
        channels: list[Literal["macos", "console"]] | None = None,
        now_dt: datetime | None = None,
    ) -> tuple[list[ProactiveAlert], list[tuple[ProactiveAlert, str]]]:
        """Execute a single proactive evaluation pass.

        Args:
            notify: Whether to dispatch notifications (desktop, console).
            dry_run: If True, do not mutate daemon_state.json.
            bypass_filters: If True, bypass quiet hours and rate limits.
            channels: Channels to notify ("macos", "console").
            now_dt: Reference time (defaults to now).

        Returns:
            (actionable_alerts, squelched_alerts_with_reasons)
        """
        now = now_dt or datetime.now()
        if not dry_run:
            fast_path.run_idea_decay(self.data_dir)

        actionable, squelched = evaluate_knowledge_state(
            self.data_dir,
            now_dt=now,
            bypass_filters=bypass_filters,
        )

        if actionable and not dry_run:
            state = load_daemon_state(self.data_dir)
            for alert in actionable:
                state.record_notification(
                    item_id=alert.item_id,
                    item_type=alert.item_type,
                    urgency_tier=alert.urgency_tier,
                    reason=alert.title,
                    now_dt=now,
                )
            save_daemon_state(state, self.data_dir)

        if notify and actionable:
            NotificationDispatcher.dispatch(
                actionable,
                channels=channels,
                data_dir=self.data_dir,
            )

        return actionable, squelched

    def run_loop(self, interval_seconds: int = 900) -> None:
        """Run continuous polling loop.

        Args:
            interval_seconds: Check interval in seconds (default: 15 minutes).
        """
        while True:
            try:
                self.run_once(notify=True, dry_run=False)
            except Exception as e:
                print(f"[Marvin Daemon Error] {e}", file=sys.stderr)

            time.sleep(interval_seconds)

    def get_ambient_status(self, use_emojis: bool = True) -> str:
        """Compute counts and return single-line status string."""
        tf = fast_path.load_tasks(self.data_dir)
        ideas = fast_path.load_ideas(self.data_dir)
        state = load_daemon_state(self.data_dir)

        from datetime import date as _date
        today = _date.today()
        now_dt = datetime.now()

        def is_snoozed(item_id: str) -> bool:
            return state.get_active_snooze(item_id, now_dt) is not None

        overdue_count = sum(1 for t in tf.open_tasks if t.is_overdue(today=today) and not is_snoozed(t.id))
        due_today_count = sum(1 for t in tf.open_tasks if t.deadline == today and not is_snoozed(t.id))
        blocker_count = sum(1 for t in tf.open_tasks if t.waiting_on and not is_snoozed(t.id))

        expiring_ideas_count = 0
        for idea in ideas.ideas:
            if idea.status in ("spark", "developing") and not is_snoozed(idea.id):
                left = idea.days_until_archive(today)
                if left is not None and left <= 5:
                    expiring_ideas_count += 1

        return AmbientStatusFormatter.format_status(
            due_today_count=due_today_count,
            overdue_count=overdue_count,
            blocker_count=blocker_count,
            expiring_ideas_count=expiring_ideas_count,
            use_emojis=use_emojis,
        )

    # ------------------------------------------------------------------
    # macOS Launchd integration
    # ------------------------------------------------------------------

    @staticmethod
    def get_launchd_plist_path() -> Path:
        """Get path to ~/Library/LaunchAgents/com.noa.marvin.daemon.plist."""
        return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"

    def generate_launchd_plist(self, interval_seconds: int = 900) -> str:
        """Generate XML plist for macOS Launchd agent."""
        marvin_bin = shutil.which("marvin") or sys.executable
        args_str = f"        <string>{marvin_bin}</string>\n"
        if marvin_bin == sys.executable:
            args_str += (
                f"        <string>-m</string>\n"
                f"        <string>marvin.cli</string>\n"
            )
        args_str += (
            f"        <string>daemon</string>\n"
            f"        <string>run-once</string>\n"
            f"        <string>--no-console</string>\n"
        )

        log_dir = Path.home() / ".marvin" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = str(log_dir / "daemon.stdout.log")
        stderr_path = str(log_dir / "daemon.stderr.log")

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCHD_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
{args_str}    </array>
    <key>StartInterval</key>
    <integer>{interval_seconds}</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{stdout_path}</string>
    <key>StandardErrorPath</key>
    <string>{stderr_path}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>MARVIN_DATA_DIR</key>
        <string>{self.data_dir}</string>
    </dict>
</dict>
</plist>
"""

    def install_launchd_service(self, interval_seconds: int = 900) -> bool:
        """Install and load the launchd agent."""
        plist_path = self.get_launchd_plist_path()
        plist_path.parent.mkdir(parents=True, exist_ok=True)

        plist_content = self.generate_launchd_plist(interval_seconds)
        plist_path.write_text(plist_content)

        try:
            # Unload first if previously loaded
            subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
            res = subprocess.run(["launchctl", "load", str(plist_path)], capture_output=True, check=True)
            return res.returncode == 0
        except Exception:
            return False

    def uninstall_launchd_service(self) -> bool:
        """Unload and remove the launchd agent."""
        plist_path = self.get_launchd_plist_path()
        if not plist_path.exists():
            return True

        try:
            subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
            plist_path.unlink(missing_ok=True)
            return True
        except Exception:
            return False
