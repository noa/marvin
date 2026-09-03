"""Tests for Microsoft Graph client with OAuth2 Device Code Flow and API queries."""

import json
import time
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from marvin.email_client import (
    AuthenticationError,
    DeviceCodeExpiredError,
    MicrosoftGraphClient,
    NotAuthenticatedError,
)
from marvin.email_schema import EmailAuthTokens, save_email_auth


def test_initiate_device_flow(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/oauth2/v2.0/devicecode")
        assert b"client_id=" in request.content
        return httpx.Response(
            200,
            json={
                "user_code": "ABCD-EFGH",
                "device_code": "dev-12345",
                "verification_uri": "https://microsoft.com/devicelogin",
                "expires_in": 900,
                "interval": 5,
                "message": "To sign in, use a web browser to open https://microsoft.com/devicelogin",
            },
        )

    client = MicrosoftGraphClient(tmp_path, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    flow = client.initiate_device_flow()
    assert flow["user_code"] == "ABCD-EFGH"
    assert flow["device_code"] == "dev-12345"
    assert flow["verification_uri"] == "https://microsoft.com/devicelogin"


def test_poll_device_token_success(tmp_path: Path):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path.endswith("/oauth2/v2.0/token"):
            if calls == 1:
                return httpx.Response(400, json={"error": "authorization_pending"})
            return httpx.Response(
                200,
                json={
                    "access_token": "acc-token-123",
                    "refresh_token": "ref-token-456",
                    "expires_in": 3600,
                    "scope": "offline_access Mail.Read User.Read",
                },
            )
        elif request.url.path.endswith("/v1.0/me"):
            return httpx.Response(
                200,
                json={
                    "displayName": "Professor Nick Andrews",
                    "mail": "noa@jhu.edu",
                    "userPrincipalName": "noa@jhu.edu",
                },
            )
        return httpx.Response(404)

    client = MicrosoftGraphClient(tmp_path, http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    with patch("time.sleep", return_value=None):
        tokens = client.poll_device_token("dev-code", interval=1, expires_in=10)

    assert tokens.access_token == "acc-token-123"
    assert tokens.refresh_token == "ref-token-456"
    assert tokens.account_email == "noa@jhu.edu"
    assert tokens.account_name == "Professor Nick Andrews"
    assert client.is_logged_in()


def test_poll_device_token_expired(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "expired_token"})

    client = MicrosoftGraphClient(tmp_path, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(DeviceCodeExpiredError):
        client.poll_device_token("dev-code", interval=1, expires_in=10)


def test_refresh_token(tmp_path: Path):
    initial_tokens = EmailAuthTokens(
        client_id="cid-1",
        tenant_id="organizations",
        account_email="noa@jhu.edu",
        access_token="old-token",
        refresh_token="old-refresh",
        expires_at=time.time() - 10,
        scopes=["Mail.Read"],
    )
    save_email_auth(initial_tokens, tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        assert b"grant_type=refresh_token" in request.content
        return httpx.Response(
            200,
            json={
                "access_token": "new-token",
                "refresh_token": "new-refresh",
                "expires_in": 3600,
                "scope": "Mail.Read",
            },
        )

    client = MicrosoftGraphClient(tmp_path, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    valid = client.get_valid_tokens()
    assert valid.access_token == "new-token"
    assert valid.refresh_token == "new-refresh"
    assert valid.expires_at > time.time()


def test_list_messages(tmp_path: Path):
    auth = EmailAuthTokens(
        client_id="cid",
        tenant_id="org",
        account_email="noa@jhu.edu",
        access_token="valid-token",
        expires_at=time.time() + 3600,
    )
    save_email_auth(auth, tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        from urllib.parse import unquote_plus
        assert request.headers["Authorization"] == "Bearer valid-token"
        url_str = unquote_plus(str(request.url))
        assert "$top=5" in url_str
        assert "isRead eq false" in url_str
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "msg-1",
                        "subject": "Paper revision",
                        "from": {"emailAddress": {"name": "Alice Chen", "address": "alice@jhu.edu"}},
                        "receivedDateTime": "2026-09-02T12:00:00Z",
                        "bodyPreview": "Uploaded revised manuscript",
                        "importance": "normal",
                        "isRead": False,
                    }
                ]
            },
        )

    client = MicrosoftGraphClient(tmp_path, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    messages = client.list_messages(limit=5, unread_only=True)
    assert len(messages) == 1
    assert messages[0].id == "msg-1"
    assert messages[0].subject == "Paper revision"
    assert messages[0].sender is not None
    assert messages[0].sender.address == "alice@jhu.edu"


def test_get_message(tmp_path: Path):
    auth = EmailAuthTokens(
        client_id="cid",
        tenant_id="org",
        account_email="noa@jhu.edu",
        access_token="valid-token",
        expires_at=time.time() + 3600,
    )
    save_email_auth(auth, tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "msg-99",
                "subject": "Conference Update",
                "from": {"emailAddress": {"name": "Chair", "address": "chair@icml.cc"}},
                "body": {"contentType": "text", "content": "Notifications are out."},
                "receivedDateTime": "2026-09-02T10:00:00Z",
                "isRead": True,
            },
        )

    client = MicrosoftGraphClient(tmp_path, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    msg = client.get_message("msg-99")
    assert msg.id == "msg-99"
    assert msg.subject == "Conference Update"
    assert msg.clean_text_body() == "Notifications are out."


def test_mark_as_read(tmp_path: Path):
    auth = EmailAuthTokens(
        client_id="cid",
        tenant_id="org",
        account_email="noa@jhu.edu",
        access_token="valid-token",
        expires_at=time.time() + 3600,
    )
    save_email_auth(auth, tmp_path)

    def handler_200(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    client = MicrosoftGraphClient(tmp_path, http_client=httpx.Client(transport=httpx.MockTransport(handler_200)))
    assert client.mark_as_read("msg-1") is True

    # When scope is Mail.Read only, Graph returns 403 Forbidden
    def handler_403(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"code": "ErrorAccessDenied"}})

    client_ro = MicrosoftGraphClient(tmp_path, http_client=httpx.Client(transport=httpx.MockTransport(handler_403)))
    assert client_ro.mark_as_read("msg-1") is False
