"""Tests for Always-On daemon CLI commands in marvin.cli."""

import json
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from marvin.cli import main
from marvin.task_schema import Task, TaskFile, save_task_file
from marvin.collaborator_schema import CollaboratorFile, save_collaborator_file
from marvin.idea_schema import IdeaFile, save_idea_file


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    """Set up data directory and bypass setup check."""
    (tmp_path / "tasks.json").write_text('{"project": "default", "tasks": []}')
    (tmp_path / "collaborators.json").write_text('{"collaborators": []}')
    (tmp_path / "ideas.json").write_text('{"ideas": []}')

    monkeypatch.setattr("marvin.cli.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("marvin.cli.is_setup_complete", lambda: True)

    return tmp_path


@pytest.fixture
def runner():
    return CliRunner()


def test_status_ambient_empty(runner, cli_env):
    """Test marvin status --ambient on empty database."""
    res = runner.invoke(main, ["status", "--ambient"])
    assert res.exit_code == 0
    assert "all clear" in res.output


def test_status_ambient_with_tasks(runner, cli_env):
    """Test marvin status --ambient with overdue and due today tasks."""
    today = date.today()
    tf = TaskFile(
        project="default",
        tasks=[
            Task(id="t1", description="Overdue item", deadline=today - timedelta(days=2)),
            Task(id="t2", description="Due today item", deadline=today),
            Task(id="t3", description="Waiting item", waiting_on="Alice"),
        ],
    )
    save_task_file(tf, cli_env / "tasks.json")

    res = runner.invoke(main, ["status", "--ambient"])
    assert res.exit_code == 0
    assert "1 overdue" in res.output
    assert "1 due today" in res.output
    assert "1 waiting" in res.output


def test_daemon_status_command(runner, cli_env):
    """Test marvin daemon status output."""
    res = runner.invoke(main, ["daemon", "status"])
    assert res.exit_code == 0
    assert "Daemon Configuration" in res.output
    assert "Quiet Hours" in res.output
    assert "Max Daily Pings" in res.output


def test_daemon_run_once_dry_run(runner, cli_env):
    """Test marvin daemon run-once in dry-run mode."""
    today = date.today()
    tf = TaskFile(
        project="default",
        tasks=[
            Task(id="t1", description="Urgent report", deadline=today, priority="high"),
        ],
    )
    save_task_file(tf, cli_env / "tasks.json")

    res = runner.invoke(main, ["daemon", "run-once", "--dry-run", "--force"])
    assert res.exit_code == 0
    assert "Urgent report" in res.output


def test_daemon_snooze_and_unsnooze(runner, cli_env):
    """Test marvin daemon snooze and unsnooze commands."""
    res_snooze = runner.invoke(main, ["daemon", "snooze", "ae23", "--days", "2", "--reason", "Waiting on funding"])
    assert res_snooze.exit_code == 0
    assert "Snoozed alerts for 'ae23'" in res_snooze.output

    # Check that status shows the active snooze
    res_status = runner.invoke(main, ["daemon", "status"])
    assert res_status.exit_code == 0
    assert "ae23" in res_status.output
    assert "Waiting on funding" in res_status.output

    # Unsnooze
    res_unsnooze = runner.invoke(main, ["daemon", "unsnooze", "ae23"])
    assert res_unsnooze.exit_code == 0
    assert "Removed snooze for 'ae23'" in res_unsnooze.output


def test_daemon_install_and_uninstall(runner, cli_env):
    """Test marvin daemon install and uninstall with mocked launchctl."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)

        res_install = runner.invoke(main, ["daemon", "install", "--interval", "600"])
        assert res_install.exit_code == 0
        assert "Launchd daemon installed" in res_install.output

        res_uninstall = runner.invoke(main, ["daemon", "uninstall"])
        assert res_uninstall.exit_code == 0
        assert "Launchd daemon uninstalled" in res_uninstall.output
