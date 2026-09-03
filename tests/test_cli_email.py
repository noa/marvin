"""Tests for email CLI commands (marvin email ...)."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from marvin.cli import main
from marvin.email_schema import EmailAddress, EmailAuthTokens, EmailMessage, save_email_auth
from marvin.task_schema import Task, TaskFile, save_task_file


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch):
    (tmp_path / "tasks.json").write_text('{"project": "default", "tasks": []}')
    (tmp_path / "collaborators.json").write_text('{"collaborators": []}')
    (tmp_path / "ideas.json").write_text('{"ideas": []}')

    monkeypatch.setattr("marvin.cli.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("marvin.cli.is_setup_complete", lambda: True)
    return tmp_path


@pytest.fixture
def runner():
    return CliRunner()


def test_cli_email_status_unauthenticated(runner, cli_env: Path):
    result = runner.invoke(main, ["email", "status"])
    assert result.exit_code == 0
    assert "Not signed in to Microsoft 365" in result.output
    assert "marvin email login" in result.output


def test_cli_email_status_authenticated(runner, cli_env: Path):
    tokens = EmailAuthTokens(
        client_id="app-12345",
        tenant_id="organizations",
        account_email="noa@jhu.edu",
        account_name="Nick Andrews",
        access_token="tok",
        expires_at=time.time() + 3600,
        scopes=["Mail.Read", "User.Read"],
    )
    save_email_auth(tokens, cli_env)

    result = runner.invoke(main, ["email", "status"])
    assert result.exit_code == 0
    assert "Nick Andrews <noa@jhu.edu>" in result.output
    assert "app-12345" in result.output
    assert "Active" in result.output


def test_cli_email_list(runner, cli_env: Path):
    tokens = EmailAuthTokens(
        client_id="app-123",
        tenant_id="org",
        account_email="noa@jhu.edu",
        access_token="tok",
        expires_at=time.time() + 3600,
    )
    save_email_auth(tokens, cli_env)

    mock_messages = [
        EmailMessage(
            id="msg-1001",
            subject="Grant notification",
            sender=EmailAddress(name="Sponsor", address="sponsor@nih.gov"),
            received_datetime=None,
            importance="high",
            is_read=False,
        )
    ]

    with patch("marvin.email_client.MicrosoftGraphClient.list_messages", return_value=mock_messages):
        result = runner.invoke(main, ["email", "list"])
        assert result.exit_code == 0
        assert "Outlook Inbox" in result.output
        assert "Grant notification" in result.output
        assert "sponsor@nih.gov" in result.output


def test_cli_email_show(runner, cli_env: Path):
    tokens = EmailAuthTokens(
        client_id="app-123",
        tenant_id="org",
        account_email="noa@jhu.edu",
        access_token="tok",
        expires_at=time.time() + 3600,
    )
    save_email_auth(tokens, cli_env)

    mock_msg = EmailMessage(
        id="msg-2002",
        subject="Meeting Agenda",
        sender=EmailAddress(name="Alice Chen", address="alice@jhu.edu"),
        to_recipients=[EmailAddress(name="Nick", address="noa@jhu.edu")],
        body_content="Here is the agenda for tomorrow.",
        body_type="text",
    )

    with patch("marvin.email_client.MicrosoftGraphClient.get_message", return_value=mock_msg):
        result = runner.invoke(main, ["email", "show", "msg-2002"])
        assert result.exit_code == 0
        assert "Meeting Agenda" in result.output
        assert "Alice Chen <alice@jhu.edu>" in result.output
        assert "Here is the agenda for tomorrow." in result.output


def test_cli_email_triage(runner, cli_env: Path):
    tokens = EmailAuthTokens(
        client_id="app-123",
        tenant_id="org",
        account_email="noa@jhu.edu",
        access_token="tok",
        expires_at=time.time() + 3600,
    )
    save_email_auth(tokens, cli_env)

    mock_messages = [
        EmailMessage(
            id="msg-triage-1",
            subject="Please review student paper",
            sender=EmailAddress(name="Editor", address="editor@acm.org"),
            body_preview="Review due soon.",
            is_read=False,
        )
    ]

    with patch("marvin.email_client.MicrosoftGraphClient.list_messages", return_value=mock_messages), \
         patch("marvin.email_client.MicrosoftGraphClient.mark_as_read", return_value=True):
        # User input: 't' (task) -> Task description (Enter default) -> Deadline (Enter skip) -> Priority (high) -> 'q'
        user_inputs = "\n".join(["t", "Review student paper", "", "high", "q"])
        result = runner.invoke(main, ["email", "triage"], input=user_inputs)
        assert result.exit_code == 0
        assert "Created task" in result.output

    # Verify task was added
    tf_data = json.loads((cli_env / "tasks.json").read_text())
    assert len(tf_data["tasks"]) == 1
    assert tf_data["tasks"][0]["description"] == "Review student paper"
    assert tf_data["tasks"][0]["priority"] == "high"


def test_cli_email_logout(runner, cli_env: Path):
    tokens = EmailAuthTokens(
        client_id="app-123",
        tenant_id="org",
        account_email="noa@jhu.edu",
        access_token="tok",
        expires_at=time.time() + 3600,
    )
    save_email_auth(tokens, cli_env)

    result = runner.invoke(main, ["email", "logout"])
    assert result.exit_code == 0
    assert "Signed out from Microsoft Graph" in result.output
    assert not (cli_env / "email_auth.json").exists()
