"""Pydantic schemas and persistence for Microsoft Graph email integration."""

import html
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field


def _strip_html(html_str: str) -> str:
    """Convert HTML string into clean plain text."""
    if not html_str:
        return ""
    # Remove style and script blocks
    text = re.sub(r"<(style|script)[^>]*>.*?</\1>", "", html_str, flags=re.DOTALL | re.IGNORECASE)
    # Replace breaks and paragraphs with newlines
    text = re.sub(r"<(br|p|div|tr)[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Strip remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Unescape HTML entities (&nbsp;, &amp;, etc.)
    text = html.unescape(text)
    # Normalize multiple whitespace and excessive newlines
    lines = [line.strip() for line in text.splitlines()]
    clean_lines: list[str] = []
    prev_empty = False
    for line in lines:
        if not line:
            if not prev_empty:
                clean_lines.append("")
                prev_empty = True
        else:
            clean_lines.append(line)
            prev_empty = False
    return "\n".join(clean_lines).strip()


class EmailAddress(BaseModel):
    """Email address representation from Microsoft Graph."""

    name: str | None = None
    address: str

    @classmethod
    def from_graph_dict(cls, data: dict[str, Any] | None) -> "EmailAddress | None":
        if not data:
            return None
        email_obj = data.get("emailAddress", data)
        address = email_obj.get("address", "")
        if not address:
            return None
        return cls(name=email_obj.get("name") or None, address=address)

    def display(self) -> str:
        if self.name and self.name != self.address:
            return f"{self.name} <{self.address}>"
        return self.address


class EmailMessage(BaseModel):
    """Microsoft Graph Outlook email message representation."""

    id: str
    conversation_id: str | None = None
    subject: str = "(No subject)"
    sender: EmailAddress | None = None
    to_recipients: list[EmailAddress] = Field(default_factory=list)
    cc_recipients: list[EmailAddress] = Field(default_factory=list)
    received_datetime: datetime | None = None
    body_preview: str = ""
    body_content: str = ""
    body_type: str = "text"
    has_attachments: bool = False
    importance: str = "normal"  # low, normal, high
    is_read: bool = False
    web_link: str | None = None

    @property
    def short_id(self) -> str:
        """First 8 characters of message ID."""
        return self.id[:8]

    @classmethod
    def from_graph_dict(cls, data: dict[str, Any]) -> "EmailMessage":
        sender_data = data.get("from") or data.get("sender")
        sender = EmailAddress.from_graph_dict(sender_data)

        to_recips: list[EmailAddress] = []
        for r in data.get("toRecipients", []):
            addr = EmailAddress.from_graph_dict(r)
            if addr:
                to_recips.append(addr)

        cc_recips: list[EmailAddress] = []
        for r in data.get("ccRecipients", []):
            addr = EmailAddress.from_graph_dict(r)
            if addr:
                cc_recips.append(addr)

        dt = None
        raw_dt = data.get("receivedDateTime")
        if raw_dt:
            try:
                # Graph returns ISO 8601 like 2026-09-02T18:42:00Z
                dt = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
            except ValueError:
                dt = None

        body_obj = data.get("body", {})
        body_content = body_obj.get("content", "")
        body_type = body_obj.get("contentType", "text").lower()

        return cls(
            id=data["id"],
            conversation_id=data.get("conversationId"),
            subject=data.get("subject") or "(No subject)",
            sender=sender,
            to_recipients=to_recips,
            cc_recipients=cc_recips,
            received_datetime=dt,
            body_preview=data.get("bodyPreview") or "",
            body_content=body_content,
            body_type=body_type,
            has_attachments=bool(data.get("hasAttachments", False)),
            importance=data.get("importance", "normal").lower(),
            is_read=bool(data.get("isRead", False)),
            web_link=data.get("webLink"),
        )

    def clean_text_body(self) -> str:
        """Return clean plain-text version of email body."""
        if self.body_type == "html":
            return _strip_html(self.body_content)
        return self.body_content.strip()


class EmailAuthTokens(BaseModel):
    """Stored OAuth2 tokens and metadata for Microsoft Graph."""

    client_id: str
    tenant_id: str = "organizations"
    account_email: str | None = None
    account_name: str | None = None
    access_token: str
    refresh_token: str | None = None
    expires_at: float  # Unix epoch timestamp
    scopes: list[str] = Field(default_factory=list)

    def is_expired(self, buffer_seconds: int = 300) -> bool:
        """Check whether the access token is expired (or expiring soon)."""
        return (time.time() + buffer_seconds) >= self.expires_at


class EmailState(BaseModel):
    """Persisted triage state tracking processed emails and task links."""

    triaged_ids: list[str] = Field(default_factory=list)
    created_tasks: dict[str, str] = Field(default_factory=dict)  # email_id -> task_id
    last_sync_at: datetime | None = None

    def is_triaged(self, email_id: str) -> bool:
        return email_id in self.triaged_ids

    def mark_triaged(self, email_id: str, task_id: str | None = None) -> None:
        if email_id not in self.triaged_ids:
            self.triaged_ids.append(email_id)
        if task_id:
            self.created_tasks[email_id] = task_id

    def unmark_triaged(self, email_id: str) -> None:
        if email_id in self.triaged_ids:
            self.triaged_ids.remove(email_id)
        self.created_tasks.pop(email_id, None)


# ---------------------------------------------------------------------------
# Storage Functions
# ---------------------------------------------------------------------------

def get_email_auth_path(data_dir: Path) -> Path:
    """Path to email_auth.json."""
    return data_dir / "email_auth.json"


def get_email_state_path(data_dir: Path) -> Path:
    """Path to email_state.json."""
    return data_dir / "email_state.json"


def load_email_auth(data_dir: Path) -> EmailAuthTokens | None:
    """Load authentication tokens from data directory."""
    path = get_email_auth_path(data_dir)
    if not path.exists():
        return None
    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
        return EmailAuthTokens.model_validate(data)
    except Exception:
        return None


def save_email_auth(auth: EmailAuthTokens, data_dir: Path) -> None:
    """Save authentication tokens with restricted (0600) file permissions."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = get_email_auth_path(data_dir)
    content = auth.model_dump_json(indent=2)
    path.write_text(content, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def delete_email_auth(data_dir: Path) -> bool:
    """Delete authentication tokens (logout). Returns True if deleted."""
    path = get_email_auth_path(data_dir)
    if path.exists():
        try:
            path.unlink()
            return True
        except OSError:
            return False
    return False


def load_email_state(data_dir: Path) -> EmailState:
    """Load local triage state."""
    path = get_email_state_path(data_dir)
    if not path.exists():
        return EmailState()
    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
        return EmailState.model_validate(data)
    except Exception:
        return EmailState()


def save_email_state(state: EmailState, data_dir: Path) -> None:
    """Save local triage state."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = get_email_state_path(data_dir)
    content = state.model_dump_json(indent=2)
    path.write_text(content, encoding="utf-8")
