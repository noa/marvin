"""Tests for proactive tools exposed by Marvin MCP server."""

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from marvin.task_schema import Task, TaskFile, save_task_file
from marvin.collaborator_schema import CollaboratorFile, save_collaborator_file
from marvin.idea_schema import IdeaFile, save_idea_file
from marvin.daemon_schema import load_daemon_state


def test_mcp_proactive_pings(tmp_path: Path):
    """Test get_proactive_pings tool execution."""
    today = date.today()
    tf = TaskFile(
        project="default",
        tasks=[
            Task(id="t1", description="Urgent submission", deadline=today, priority="high"),
        ],
    )
    save_task_file(tf, tmp_path / "tasks.json")
    save_collaborator_file(CollaboratorFile(), tmp_path / "collaborators.json")
    save_idea_file(IdeaFile(), tmp_path / "ideas.json")

    from marvin.daemon import MarvinDaemon
    daemon = MarvinDaemon(tmp_path)
    actionable, squelched = daemon.run_once(notify=False, dry_run=True, bypass_filters=True)

    assert len(actionable) == 1
    assert actionable[0].item_id == "t1"
    assert actionable[0].urgency_tier == "due_today"


def test_mcp_snooze_alert(tmp_path: Path):
    """Test snooze_alert tool execution."""
    from marvin.daemon_schema import load_daemon_state, save_daemon_state

    state = load_daemon_state(tmp_path)
    now = datetime.now()
    target_dt = now + timedelta(days=2)

    state.snooze("t1", target_dt, reason="Waiting for committee", now_dt=now)
    save_daemon_state(state, tmp_path)

    loaded = load_daemon_state(tmp_path)
    snooze = loaded.get_active_snooze("t1", now)
    assert snooze is not None
    assert snooze.reason == "Waiting for committee"


def test_mcp_unsnooze_alert(tmp_path: Path):
    """Test unsnooze_alert tool execution."""
    from marvin.daemon_schema import load_daemon_state, save_daemon_state

    state = load_daemon_state(tmp_path)
    now = datetime.now()
    state.snooze("ae23f1", now + timedelta(days=2), reason="Testing", now_dt=now)
    save_daemon_state(state, tmp_path)

    # Prefix unsnooze
    state = load_daemon_state(tmp_path)
    assert state.unsnooze("ae23") is True
    save_daemon_state(state, tmp_path)

    loaded = load_daemon_state(tmp_path)
    assert loaded.get_active_snooze("ae23f1", now) is None


def test_mcp_proactive_pings_with_email(tmp_path: Path):
    """Test get_proactive_pings includes email blocker alerts."""
    from marvin.email_schema import EmailAddress, EmailMessage
    from unittest.mock import MagicMock
    from marvin.daemon import MarvinDaemon

    c_file = CollaboratorFile(collaborators=[])
    save_collaborator_file(c_file, tmp_path / "collaborators.json")
    save_idea_file(IdeaFile(), tmp_path / "ideas.json")
    save_task_file(TaskFile(project="default", tasks=[]), tmp_path / "tasks.json")

    mock_msg = EmailMessage(
        id="msg-mcp-1",
        subject="Action Required: Review NIH proposal",
        sender=EmailAddress(name="Sponsor", address="sponsor@nih.gov"),
        importance="high",
        is_read=False,
    )
    mock_client = MagicMock()
    mock_client.list_messages.return_value = [mock_msg]

    daemon = MarvinDaemon(tmp_path)
    actionable, _ = daemon.run_once(
        notify=False,
        dry_run=True,
        bypass_filters=True,
        email_client=mock_client,
    )

    assert len(actionable) == 1
    assert actionable[0].item_id == "msg-mcp-1"
    assert actionable[0].category == "triage"
    assert actionable[0].item_type == "email"
