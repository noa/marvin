"""Microsoft Graph Outlook client supporting OAuth2 Device Code Flow and Graph API v1.0."""

import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable

import httpx

from marvin.email_schema import (
    EmailAddress,
    EmailAuthTokens,
    EmailMessage,
    delete_email_auth,
    load_email_auth,
    save_email_auth,
)

# Official Microsoft Graph Command Line Tools public client ID
# Pre-consented across Entra ID / Microsoft 365 tenants
DEFAULT_CLIENT_ID = "14d82eec-204b-4a2f-b3e8-29561ee34374"
# Alternative well-known client ID: Azure CLI ("04b07795-8ddb-461a-bbee-02f9e1bf7b46")

DEFAULT_TENANT = "organizations"
DEFAULT_SCOPES = ["offline_access", "User.Read", "Mail.Read"]

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"


class EmailClientError(Exception):
    """Base exception for email client errors."""


class NotAuthenticatedError(EmailClientError):
    """Raised when user is not logged in or credentials are missing."""


class AuthenticationError(EmailClientError):
    """Raised when authentication fails."""


class DeviceCodeExpiredError(AuthenticationError):
    """Raised when device authorization code expires before approval."""


class MicrosoftGraphClient:
    """Client for Microsoft Graph Outlook mail operations."""

    def __init__(
        self,
        data_dir: Path,
        client_id: str | None = None,
        tenant: str | None = None,
        http_client: httpx.Client | None = None,
    ):
        self.data_dir = data_dir
        self._custom_client_id = client_id
        self._custom_tenant = tenant
        self._http = http_client or httpx.Client(timeout=30.0)

    @property
    def client_id(self) -> str:
        """Resolve client ID from param, env, saved tokens, or default."""
        if self._custom_client_id:
            return self._custom_client_id
        env_id = os.environ.get("MARVIN_AZURE_CLIENT_ID")
        if env_id:
            return env_id
        tokens = load_email_auth(self.data_dir)
        if tokens and tokens.client_id:
            return tokens.client_id
        return DEFAULT_CLIENT_ID

    @property
    def tenant(self) -> str:
        """Resolve tenant ID from param, env, saved tokens, or default."""
        if self._custom_tenant:
            return self._custom_tenant
        env_tenant = os.environ.get("MARVIN_AZURE_TENANT") or os.environ.get("MARVIN_AZURE_TENANT_ID")
        if env_tenant:
            return env_tenant
        tokens = load_email_auth(self.data_dir)
        if tokens and tokens.tenant_id:
            return tokens.tenant_id
        return DEFAULT_TENANT

    # -----------------------------------------------------------------------
    # Authentication & OAuth2 Device Code Flow
    # -----------------------------------------------------------------------

    def initiate_device_flow(
        self,
        client_id: str | None = None,
        tenant: str | None = None,
        scopes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Initiate OAuth 2.0 Device Authorization Flow.

        Returns device code response containing user_code and verification_uri.
        """
        cid = client_id or self.client_id
        t = tenant or self.tenant
        sc = scopes or DEFAULT_SCOPES

        url = f"https://login.microsoftonline.com/{t}/oauth2/v2.0/devicecode"
        resp = self._http.post(
            url,
            data={
                "client_id": cid,
                "scope": " ".join(sc),
            },
        )

        if resp.status_code != 200:
            err_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            msg = err_data.get("error_description") or resp.text
            raise AuthenticationError(f"Failed to initiate device login: {msg}")

        return resp.json()

    def poll_device_token(
        self,
        device_code: str,
        interval: int = 5,
        expires_in: int = 900,
        client_id: str | None = None,
        tenant: str | None = None,
        scopes: list[str] | None = None,
        poll_callback: Callable[[int], None] | None = None,
    ) -> EmailAuthTokens:
        """Poll token endpoint until device code flow is authorized or expired."""
        cid = client_id or self.client_id
        t = tenant or self.tenant
        sc = scopes or DEFAULT_SCOPES

        url = f"https://login.microsoftonline.com/{t}/oauth2/v2.0/token"
        start_time = time.time()
        poll_count = 0

        while True:
            if time.time() - start_time > expires_in:
                raise DeviceCodeExpiredError("Device code expired. Please log in again.")

            poll_count += 1
            if poll_callback:
                poll_callback(poll_count)

            resp = self._http.post(
                url,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": cid,
                    "device_code": device_code,
                },
            )

            if resp.status_code == 200:
                data = resp.json()
                expires_at = time.time() + float(data.get("expires_in", 3600))
                tokens = EmailAuthTokens(
                    client_id=cid,
                    tenant_id=t,
                    access_token=data["access_token"],
                    refresh_token=data.get("refresh_token"),
                    expires_at=expires_at,
                    scopes=data.get("scope", "").split(),
                )

                # Query /me to get user display name and email
                try:
                    profile = self._get_user_profile_with_token(tokens.access_token)
                    tokens.account_name = profile.get("displayName")
                    tokens.account_email = profile.get("mail") or profile.get("userPrincipalName")
                except Exception:
                    pass

                save_email_auth(tokens, self.data_dir)
                return tokens

            # Handle errors
            err_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            err = err_data.get("error", "")

            if err == "authorization_pending":
                time.sleep(interval)
            elif err == "slow_down":
                interval += 5
                time.sleep(interval)
            elif err == "expired_token":
                raise DeviceCodeExpiredError("Device code expired. Please run 'marvin email login' again.")
            elif err == "access_denied":
                raise AuthenticationError("Sign-in cancelled or denied by user.")
            else:
                desc = err_data.get("error_description") or resp.text
                raise AuthenticationError(f"Authentication failed: {err} - {desc}")

    def refresh_token(self, tokens: EmailAuthTokens) -> EmailAuthTokens:
        """Refresh an expired access token."""
        if not tokens.refresh_token:
            raise NotAuthenticatedError("No refresh token stored. Run 'marvin email login' to re-authenticate.")

        url = f"https://login.microsoftonline.com/{tokens.tenant_id}/oauth2/v2.0/token"
        scopes = tokens.scopes if tokens.scopes else DEFAULT_SCOPES
        resp = self._http.post(
            url,
            data={
                "grant_type": "refresh_token",
                "client_id": tokens.client_id,
                "refresh_token": tokens.refresh_token,
                "scope": " ".join(scopes),
            },
        )

        if resp.status_code != 200:
            err_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            desc = err_data.get("error_description") or resp.text
            raise AuthenticationError(f"Failed to refresh token: {desc}")

        data = resp.json()
        tokens.access_token = data["access_token"]
        if "refresh_token" in data:
            tokens.refresh_token = data["refresh_token"]
        tokens.expires_at = time.time() + float(data.get("expires_in", 3600))
        if "scope" in data:
            tokens.scopes = data["scope"].split()

        save_email_auth(tokens, self.data_dir)
        return tokens

    def get_valid_tokens(self) -> EmailAuthTokens:
        """Load stored tokens and refresh if expired."""
        tokens = load_email_auth(self.data_dir)
        if not tokens:
            raise NotAuthenticatedError(
                "Not signed in to Microsoft 365. Run 'marvin email login' to authenticate."
            )

        if tokens.is_expired():
            tokens = self.refresh_token(tokens)

        return tokens

    def logout(self) -> bool:
        """Log out by clearing stored credentials."""
        return delete_email_auth(self.data_dir)

    def is_logged_in(self) -> bool:
        """Check if authenticated credentials exist."""
        tokens = load_email_auth(self.data_dir)
        return tokens is not None

    # -----------------------------------------------------------------------
    # Graph API Endpoints
    # -----------------------------------------------------------------------

    def _get_user_profile_with_token(self, access_token: str) -> dict[str, Any]:
        resp = self._http.get(
            f"{GRAPH_API_BASE}/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if resp.status_code == 200:
            return resp.json()
        return {}

    def get_user_profile(self) -> dict[str, Any]:
        """Fetch current user's profile information from /me."""
        tokens = self.get_valid_tokens()
        return self._get_user_profile_with_token(tokens.access_token)

    def list_messages(
        self,
        limit: int = 10,
        unread_only: bool = False,
        days: int | None = None,
        folder: str = "inbox",
        query: str | None = None,
    ) -> list[EmailMessage]:
        """List email messages from Microsoft Graph.

        Args:
            limit: Maximum number of messages to return.
            unread_only: If True, only return unread messages.
            days: If provided, only return messages received within the last N days.
            folder: Mail folder name ('inbox', 'archive', etc., or 'all' for all messages).
            query: Keyword search string.
        """
        tokens = self.get_valid_tokens()

        if folder.lower() == "all":
            url = f"{GRAPH_API_BASE}/me/messages"
        else:
            url = f"{GRAPH_API_BASE}/me/mailFolders/{folder}/messages"

        params: dict[str, Any] = {
            "$top": limit,
            "$orderby": "receivedDateTime desc",
            "$select": "id,conversationId,subject,from,toRecipients,ccRecipients,receivedDateTime,bodyPreview,hasAttachments,importance,isRead,webLink",
        }

        filter_clauses: list[str] = []
        if unread_only:
            filter_clauses.append("isRead eq false")
        if days is not None and days > 0:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
            filter_clauses.append(f"receivedDateTime ge {cutoff}")

        if filter_clauses:
            params["$filter"] = " and ".join(filter_clauses)

        if query:
            params["$search"] = f'"{query}"'

        headers = {
            "Authorization": f"Bearer {tokens.access_token}",
            "Prefer": 'outlook.body-content-type="text"',
        }

        resp = self._http.get(url, params=params, headers=headers)

        if resp.status_code != 200:
            err_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            err_msg = err_data.get("error", {}).get("message") or resp.text
            raise EmailClientError(f"Graph API error ({resp.status_code}): {err_msg}")

        data = resp.json()
        messages_data = data.get("value", [])
        return [EmailMessage.from_graph_dict(m) for m in messages_data]

    def get_message(self, message_id: str) -> EmailMessage:
        """Fetch full details for a single email message."""
        tokens = self.get_valid_tokens()
        url = f"{GRAPH_API_BASE}/me/messages/{message_id}"
        params = {
            "$select": "id,conversationId,subject,from,toRecipients,ccRecipients,receivedDateTime,body,bodyPreview,hasAttachments,importance,isRead,webLink"
        }
        headers = {
            "Authorization": f"Bearer {tokens.access_token}",
        }

        resp = self._http.get(url, params=params, headers=headers)
        if resp.status_code != 200:
            err_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            err_msg = err_data.get("error", {}).get("message") or resp.text
            raise EmailClientError(f"Failed to fetch message {message_id}: {err_msg}")

        return EmailMessage.from_graph_dict(resp.json())

    def mark_as_read(self, message_id: str) -> bool:
        """Mark an email message as read on Microsoft Graph.

        Note: Requires Mail.ReadWrite delegated permission. If the user only
        has delegated Mail.Read, Graph returns 403 Forbidden, which is safely
        caught and returns False so local triage state can still record it.
        """
        try:
            tokens = self.get_valid_tokens()
            url = f"{GRAPH_API_BASE}/me/messages/{message_id}"
            headers = {
                "Authorization": f"Bearer {tokens.access_token}",
                "Content-Type": "application/json",
            }
            resp = self._http.patch(url, json={"isRead": True}, headers=headers)
            return resp.status_code in (200, 204)
        except Exception:
            return False
