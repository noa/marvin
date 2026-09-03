"""Tests for email schemas and persistence."""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from marvin.email_schema import (
    EmailAddress,
    EmailAuthTokens,
    EmailMessage,
    EmailState,
    delete_email_auth,
    load_email_auth,
    load_email_state,
    save_email_auth,
    save_email_state,
)


def test_email_address_from_graph_dict():
    # Standard Graph structure
    raw = {"emailAddress": {"name": "Alice Chen", "address": "alice@jhu.edu"}}
    addr = EmailAddress.from_graph_dict(raw)
    assert addr is not None
    assert addr.name == "Alice Chen"
    assert addr.address == "alice@jhu.edu"
    assert addr.display() == "Alice Chen <alice@jhu.edu>"

    # Direct address dict
    raw2 = {"address": "bob@jhu.edu"}
    addr2 = EmailAddress.from_graph_dict(raw2)
    assert addr2 is not None
    assert addr2.name is None
    assert addr2.display() == "bob@jhu.edu"

    # None input
    assert EmailAddress.from_graph_dict(None) is None
    assert EmailAddress.from_graph_dict({}) is None


def test_email_message_from_graph_dict():
    raw = {
        "id": "AAMkAGI2AAA=",
        "conversationId": "AAQkAGI2AAA=",
        "subject": "Paper Draft Feedback",
        "from": {"emailAddress": {"name": "Alice Chen", "address": "alice@jhu.edu"}},
        "toRecipients": [
            {"emailAddress": {"name": "Nick Andrews", "address": "noa@jhu.edu"}}
        ],
        "ccRecipients": [],
        "receivedDateTime": "2026-09-02T18:00:00Z",
        "bodyPreview": "Here is the updated draft.",
        "body": {
            "contentType": "html",
            "content": "<html><body><p>Here is the <b>updated draft</b>.</p><br><p>Best,<br>Alice</p></body></html>",
        },
        "hasAttachments": True,
        "importance": "high",
        "isRead": False,
        "webLink": "https://outlook.office.com/mail/id/123",
    }

    msg = EmailMessage.from_graph_dict(raw)
    assert msg.id == "AAMkAGI2AAA="
    assert msg.short_id == "AAMkAGI2"
    assert msg.subject == "Paper Draft Feedback"
    assert msg.sender is not None
    assert msg.sender.address == "alice@jhu.edu"
    assert len(msg.to_recipients) == 1
    assert msg.importance == "high"
    assert msg.is_read is False
    assert msg.has_attachments is True

    # Check clean body conversion
    clean_body = msg.clean_text_body()
    assert "Here is the updated draft." in clean_body
    assert "Best," in clean_body
    assert "<html>" not in clean_body


def test_email_auth_tokens_expiration():
    tokens = EmailAuthTokens(
        client_id="test-client-id",
        tenant_id="organizations",
        account_email="noa@jhu.edu",
        access_token="fake-token",
        refresh_token="fake-refresh",
        expires_at=time.time() + 600,
        scopes=["Mail.Read", "User.Read"],
    )

    assert not tokens.is_expired(buffer_seconds=60)
    assert tokens.is_expired(buffer_seconds=700)


def test_save_and_load_email_auth(tmp_path: Path):
    tokens = EmailAuthTokens(
        client_id="client-123",
        tenant_id="organizations",
        account_email="pi@jhu.edu",
        account_name="Professor Smith",
        access_token="tok-abc",
        refresh_token="ref-xyz",
        expires_at=time.time() + 3600,
        scopes=["Mail.Read"],
    )

    assert load_email_auth(tmp_path) is None

    save_email_auth(tokens, tmp_path)
    loaded = load_email_auth(tmp_path)
    assert loaded is not None
    assert loaded.client_id == "client-123"
    assert loaded.account_email == "pi@jhu.edu"
    assert loaded.account_name == "Professor Smith"
    assert loaded.access_token == "tok-abc"

    # Test delete
    assert delete_email_auth(tmp_path) is True
    assert load_email_auth(tmp_path) is None


def test_email_state_persistence(tmp_path: Path):
    state = load_email_state(tmp_path)
    assert len(state.triaged_ids) == 0

    state.mark_triaged("msg-1", "task-abc")
    state.mark_triaged("msg-2")
    assert state.is_triaged("msg-1")
    assert state.is_triaged("msg-2")
    assert state.created_tasks["msg-1"] == "task-abc"

    save_email_state(state, tmp_path)
    loaded = load_email_state(tmp_path)
    assert loaded.is_triaged("msg-1")
    assert loaded.created_tasks["msg-1"] == "task-abc"

    loaded.unmark_triaged("msg-1")
    assert not loaded.is_triaged("msg-1")
    assert "msg-1" not in loaded.created_tasks
