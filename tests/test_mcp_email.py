"""Tests for email MCP tools in Marvin."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from marvin.collaborator_schema import Collaborator, CollaboratorFile, save_collaborator_file
from marvin.email_schema import EmailAddress, EmailAuthTokens, EmailMessage, save_email_auth
from marvin.idea_schema import IdeaFile, save_idea_file
from marvin.mcp_server import create_mcp_server
from marvin.task_schema import Task, TaskFile, save_task_file


@pytest.fixture
def mcp_data_dir(tmp_path: Path) -> Path:
    tf = TaskFile(
        project="default",
        tasks=[
            Task(id="task-alice", description="Review ablation experiments", waiting_on="Alice Chen"),
        ],
    )
    save_task_file(tf, tmp_path / "tasks.json")

    cf = CollaboratorFile(
        collaborators=[
            Collaborator(
                id="collab-1",
                name="Alice Chen",
                role="PhD student",
                email="alice@jhu.edu",
            ),
        ]
    )
    save_collaborator_file(cf, tmp_path / "collaborators.json")
    save_idea_file(IdeaFile(), tmp_path / "ideas.json")
    return tmp_path


def test_mcp_get_email_status(mcp_data_dir: Path):
    mcp = create_mcp_server(mcp_data_dir)
    tool = mcp._tool_manager.get_tool("get_email_status")

    # Unauthenticated
    res = json.loads(tool.fn())
    assert res["authenticated"] is False

    # Authenticated
    tokens = EmailAuthTokens(
        client_id="app-1",
        tenant_id="organizations",
        account_email="noa@jhu.edu",
        account_name="Nick Andrews",
        access_token="tok",
        expires_at=time.time() + 3600,
        scopes=["Mail.Read", "User.Read"],
    )
    save_email_auth(tokens, mcp_data_dir)

    res_auth = json.loads(tool.fn())
    assert res_auth["authenticated"] is True
    assert res_auth["account_email"] == "noa@jhu.edu"
    assert res_auth["account_name"] == "Nick Andrews"


def test_mcp_list_emails(mcp_data_dir: Path):
    tokens = EmailAuthTokens(
        client_id="app-1",
        tenant_id="organizations",
        account_email="noa@jhu.edu",
        access_token="tok",
        expires_at=time.time() + 3600,
    )
    save_email_auth(tokens, mcp_data_dir)

    mock_msgs = [
        EmailMessage(
            id="msg-1",
            subject="Ablations are done",
            sender=EmailAddress(name="Alice Chen", address="alice@jhu.edu"),
            body_preview="Finished running the experiments.",
            is_read=False,
        )
    ]

    mcp = create_mcp_server(mcp_data_dir)
    tool = mcp._tool_manager.get_tool("list_emails")

    with patch("marvin.email_client.MicrosoftGraphClient.list_messages", return_value=mock_msgs):
        res = json.loads(tool.fn(limit=5))
        assert res["total"] == 1
        assert res["emails"][0]["subject"] == "Ablations are done"
        assert res["emails"][0]["collaborator"]["name"] == "Alice Chen"
        assert len(res["emails"][0]["waiting_tasks"]) == 1


def test_mcp_get_email(mcp_data_dir: Path):
    tokens = EmailAuthTokens(
        client_id="app-1",
        tenant_id="organizations",
        account_email="noa@jhu.edu",
        access_token="tok",
        expires_at=time.time() + 3600,
    )
    save_email_auth(tokens, mcp_data_dir)

    mock_msg = EmailMessage(
        id="msg-detail-12345",
        subject="Project Update",
        sender=EmailAddress(name="Alice Chen", address="alice@jhu.edu"),
        to_recipients=[EmailAddress(name="Nick", address="noa@jhu.edu")],
        body_content="<p>Full update text</p>",
        body_type="html",
    )

    mcp = create_mcp_server(mcp_data_dir)
    tool = mcp._tool_manager.get_tool("get_email")

    with patch("marvin.email_client.MicrosoftGraphClient.get_message", return_value=mock_msg):
        res = json.loads(tool.fn(email_id="msg-detail"))
        assert res["id"] == "msg-detail-12345"
        assert res["subject"] == "Project Update"
        assert res["body"] == "Full update text"


def test_mcp_triage_emails(mcp_data_dir: Path):
    tokens = EmailAuthTokens(
        client_id="app-1",
        tenant_id="organizations",
        account_email="noa@jhu.edu",
        access_token="tok",
        expires_at=time.time() + 3600,
    )
    save_email_auth(tokens, mcp_data_dir)

    mock_msgs = [
        EmailMessage(
            id="msg-alice",
            subject="Ablation data ready",
            sender=EmailAddress(name="Alice Chen", address="alice@jhu.edu"),
            is_read=False,
        ),
        EmailMessage(
            id="msg-grant",
            subject="Grant proposal review due Friday",
            sender=EmailAddress(name="NSF", address="fastlane@nsf.gov"),
            is_read=False,
        ),
    ]

    mcp = create_mcp_server(mcp_data_dir)
    tool = mcp._tool_manager.get_tool("triage_emails")

    with patch("marvin.email_client.MicrosoftGraphClient.list_messages", return_value=mock_msgs):
        res = json.loads(tool.fn())
        assert res["total_unread_candidates"] == 2
        # Blocker resolution detected for Alice
        assert len(res["blocker_resolutions"]) == 1
        assert res["blocker_resolutions"][0]["email_id"] == "msg-alice"
        # Suggested task detected for Grant
        assert len(res["suggested_tasks"]) == 1
        assert res["suggested_tasks"][0]["email_id"] == "msg-grant"


def test_mcp_create_task_from_email(mcp_data_dir: Path):
    tokens = EmailAuthTokens(
        client_id="app-1",
        tenant_id="organizations",
        account_email="noa@jhu.edu",
        access_token="tok",
        expires_at=time.time() + 3600,
    )
    save_email_auth(tokens, mcp_data_dir)

    mock_msg = EmailMessage(
        id="msg-create-task",
        subject="Submit workshop camera ready",
        sender=EmailAddress(name="Workshop Organizers", address="workshop@neurips.cc"),
        body_preview="Camera ready due in 2 weeks.",
        importance="high",
    )

    mcp = create_mcp_server(mcp_data_dir)
    tool = mcp._tool_manager.get_tool("create_task_from_email")

    with patch("marvin.email_client.MicrosoftGraphClient.get_message", return_value=mock_msg), \
         patch("marvin.email_client.MicrosoftGraphClient.mark_as_read", return_value=True):
        res = json.loads(tool.fn(email_id="msg-create-task", deadline="2026-09-15"))
        assert res["success"] is True
        assert res["task"]["description"] == "Submit workshop camera ready"
        assert res["task"]["deadline"] == "2026-09-15"


def test_mcp_resolve_email_blocker(mcp_data_dir: Path):
    tokens = EmailAuthTokens(
        client_id="app-1",
        tenant_id="organizations",
        account_email="noa@jhu.edu",
        access_token="tok",
        expires_at=time.time() + 3600,
    )
    save_email_auth(tokens, mcp_data_dir)

    mock_msg = EmailMessage(
        id="msg-alice-reply",
        subject="Here are the ablation charts",
        sender=EmailAddress(name="Alice Chen", address="alice@jhu.edu"),
    )

    mcp = create_mcp_server(mcp_data_dir)
    tool = mcp._tool_manager.get_tool("resolve_email_blocker")

    with patch("marvin.email_client.MicrosoftGraphClient.get_message", return_value=mock_msg), \
         patch("marvin.email_client.MicrosoftGraphClient.mark_as_read", return_value=True):
        res = json.loads(tool.fn(task_id="task-alice", email_id="msg-alice-reply"))
        assert res["success"] is True
        assert res["task"]["waiting_on"] is None
        assert any("Unblocked by email" in n for n in res["task"]["notes"])


def test_mcp_mark_email_read(mcp_data_dir: Path):
    tokens = EmailAuthTokens(
        client_id="app-1",
        tenant_id="organizations",
        account_email="noa@jhu.edu",
        access_token="tok",
        expires_at=time.time() + 3600,
    )
    save_email_auth(tokens, mcp_data_dir)

    mcp = create_mcp_server(mcp_data_dir)
    tool = mcp._tool_manager.get_tool("mark_email_read")

    with patch("marvin.email_client.MicrosoftGraphClient.mark_as_read", return_value=True):
        res = json.loads(tool.fn(email_id="msg-123456789012345678901"))
        assert res["success"] is True
