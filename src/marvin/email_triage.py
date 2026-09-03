"""Triage engine connecting Microsoft Graph emails with Marvin tasks and collaborators."""

import json
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field

from marvin import fast_path
from marvin.collaborator_schema import Collaborator, CollaboratorFile, resolve_person
from marvin.email_client import MicrosoftGraphClient
from marvin.email_schema import (
    EmailMessage,
    EmailState,
    load_email_state,
    save_email_state,
)
from marvin.task_schema import Task, TaskFile, load_task_file, save_task_file


class EmailTriageCandidate(BaseModel):
    """An email evaluated against Marvin tasks and collaborators."""

    email: EmailMessage
    collaborator: Collaborator | None = None
    waiting_tasks: list[dict[str, Any]] = Field(default_factory=list)
    suggested_action: str = "review"  # resolve_blocker, create_task, review
    urgency: str = "normal"  # low, normal, high

    def to_dict(self) -> dict[str, Any]:
        """Convert to serializable dictionary for CLI/MCP."""
        collab_dict = None
        if self.collaborator:
            collab_dict = {
                "id": self.collaborator.id,
                "short_id": self.collaborator.id[:4],
                "name": self.collaborator.name,
                "role": self.collaborator.role,
                "affiliation": self.collaborator.affiliation,
                "email": self.collaborator.email,
            }

        return {
            "email_id": self.email.id,
            "short_id": self.email.short_id,
            "subject": self.email.subject,
            "from_name": self.email.sender.name if self.email.sender else None,
            "from_email": self.email.sender.address if self.email.sender else None,
            "received_at": self.email.received_datetime.isoformat() if self.email.received_datetime else None,
            "is_read": self.email.is_read,
            "importance": self.email.importance,
            "preview": self.email.body_preview,
            "collaborator": collab_dict,
            "waiting_tasks": self.waiting_tasks,
            "suggested_action": self.suggested_action,
            "urgency": self.urgency,
        }


def find_matching_collaborator(
    sender_name: str | None,
    sender_email: str | None,
    collab_file: CollaboratorFile,
) -> Collaborator | None:
    """Find a collaborator matching email address or name."""
    if not sender_email and not sender_name:
        return None

    # 1. Direct match by email
    if sender_email:
        s_email = sender_email.strip().lower()
        for c in collab_file.collaborators:
            if c.email and c.email.strip().lower() == s_email:
                return c

    # 2. Match by display name
    if sender_name:
        matched = collab_file.find_by_query(sender_name)
        if matched:
            return matched

    # 3. Try matching user part of email (e.g., "alice" in "alice@mit.edu")
    if sender_email and "@" in sender_email:
        user_part = sender_email.split("@")[0].replace(".", " ").strip()
        matched = collab_file.find_by_query(user_part)
        if matched:
            return matched

    return None


def find_tasks_waiting_on_sender(
    sender_name: str | None,
    sender_email: str | None,
    collab: Collaborator | None,
    task_file: TaskFile,
) -> list[Task]:
    """Find open tasks waiting on this sender or matched collaborator."""
    targets = set()
    if sender_name:
        targets.add(sender_name.strip().lower())
    if sender_email:
        targets.add(sender_email.strip().lower())
        if "@" in sender_email:
            targets.add(sender_email.split("@")[0].lower())

    if collab:
        targets.add(collab.name.lower())
        for a in collab.all_aliases():
            targets.add(a.lower())

    matched_tasks: list[Task] = []
    for t in task_file.open_tasks:
        if not t.waiting_on:
            continue
        w = t.waiting_on.strip().lower()
        if w in targets:
            matched_tasks.append(t)
            continue
        # Substring or token match (e.g. "Alice" in "Alice Chen")
        for target in targets:
            if target and (target in w or w in target):
                matched_tasks.append(t)
                break

    return matched_tasks


def get_triage_candidates(
    data_dir: Path,
    client: MicrosoftGraphClient,
    limit: int = 15,
    unread_only: bool = True,
    include_triaged: bool = False,
) -> list[EmailTriageCandidate]:
    """Fetch and evaluate recent emails against Marvin tasks and collaborators."""
    collab_file = fast_path.load_collaborators(data_dir)
    task_file = fast_path.load_tasks(data_dir)
    state = load_email_state(data_dir)

    messages = client.list_messages(limit=limit, unread_only=unread_only)

    candidates: list[EmailTriageCandidate] = []
    for msg in messages:
        if not include_triaged and state.is_triaged(msg.id):
            continue

        sender_name = msg.sender.name if msg.sender else None
        sender_email = msg.sender.address if msg.sender else None

        collab = find_matching_collaborator(sender_name, sender_email, collab_file)
        waiting_tasks = find_tasks_waiting_on_sender(sender_name, sender_email, collab, task_file)

        # Determine suggested action & urgency
        suggested_action = "review"
        urgency = "normal"

        if msg.importance == "high":
            urgency = "high"

        if waiting_tasks:
            suggested_action = "resolve_blocker"
            urgency = "high"
        elif re.search(r"\b(deadline|draft|review|submit|submission|proposal|grant|paper|urgent)\b", msg.subject, re.IGNORECASE):
            suggested_action = "create_task"

        formatted_waiting = [
            {
                "id": t.id,
                "short_id": t.id[:4],
                "description": t.description,
                "waiting_on": t.waiting_on,
                "deadline": t.deadline.isoformat() if t.deadline else None,
                "priority": t.priority,
            }
            for t in waiting_tasks
        ]

        candidate = EmailTriageCandidate(
            email=msg,
            collaborator=collab,
            waiting_tasks=formatted_waiting,
            suggested_action=suggested_action,
            urgency=urgency,
        )
        candidates.append(candidate)

    return candidates


# ---------------------------------------------------------------------------
# Triage Action Handlers
# ---------------------------------------------------------------------------

def resolve_email_blocker(
    data_dir: Path,
    task_id: str,
    email: EmailMessage | None = None,
    note: str | None = None,
) -> Task:
    """Clear waiting_on status on a task and add a note that it was resolved."""
    tf = fast_path.load_tasks(data_dir)
    task = next((t for t in tf.tasks if t.id == task_id or t.id.startswith(task_id)), None)
    if not task:
        raise ValueError(f"Task '{task_id}' not found")

    sender_disp = email.sender.display() if (email and email.sender) else "email"
    subject = f': "{email.subject}"' if (email and email.subject) else ""

    default_note = f"Unblocked by email from {sender_disp}{subject}"
    resolution_note = note or default_note

    task.waiting_on = None
    task.notes.append(resolution_note)

    tasks_path = fast_path.get_tasks_path(data_dir)
    save_task_file(tf, tasks_path)

    # If email provided, record in email state
    if email:
        state = load_email_state(data_dir)
        state.mark_triaged(email.id, task.id)
        save_email_state(state, data_dir)

    try:
        from marvin.index_schema import rebuild_index
        rebuild_index(data_dir)
    except Exception:
        pass

    return task


def create_task_from_email(
    data_dir: Path,
    email: EmailMessage,
    description: str | None = None,
    deadline: date | str | None = None,
    priority: str | None = None,
    waiting_on: str | None = None,
    tags: list[str] | None = None,
) -> Task:
    """Create a new task linked to an email message."""
    import uuid
    desc = description or email.subject or "Follow up on email"

    if isinstance(deadline, str) and deadline:
        deadline_date = date.fromisoformat(deadline)
    elif isinstance(deadline, date):
        deadline_date = deadline
    else:
        deadline_date = None

    task_tags = ["email"]
    if tags:
        task_tags.extend(tags)

    prio = priority or ("high" if email.importance == "high" else "medium")

    task = Task(
        id=uuid.uuid4().hex[:6],
        description=desc,
        deadline=deadline_date,
        priority=prio,
        waiting_on=waiting_on,
        tags=sorted(list(set(task_tags))),
        created_at=date.today(),
    )

    # Add reference note with sender and preview
    sender_str = email.sender.display() if email.sender else "unknown"
    preview_snippet = email.body_preview[:150] if email.body_preview else ""
    note_lines = [f"From: {sender_str}"]
    if preview_snippet:
        note_lines.append(f'"{preview_snippet}..."')
    if email.web_link:
        note_lines.append(f"Link: {email.web_link}")

    task.notes.append(" | ".join(note_lines))

    tf = fast_path.load_tasks(data_dir)
    tf.tasks.append(task)
    tasks_path = fast_path.get_tasks_path(data_dir)
    save_task_file(tf, tasks_path)

    # Mark triaged in email state
    state = load_email_state(data_dir)
    state.mark_triaged(email.id, task.id)
    save_email_state(state, data_dir)

    return task


def create_idea_from_email(
    data_dir: Path,
    email: EmailMessage,
    thought: str | None = None,
    tag: str | None = None,
) -> Any:
    """Capture an idea spark from an email message."""
    sender_str = email.sender.display() if email.sender else "unknown"
    idea_thought = thought or email.subject
    source_str = f"Email from {sender_str}: {email.subject}"

    tags = [tag] if tag else ["email"]

    idea = fast_path.add_idea(
        data_dir,
        thought=idea_thought,
        tags=tags,
        source=source_str,
    )

    # Mark triaged in email state
    state = load_email_state(data_dir)
    state.mark_triaged(email.id)
    save_email_state(state, data_dir)

    return idea


def dismiss_email(data_dir: Path, email_id: str) -> None:
    """Mark an email as triaged/dismissed without creating a task."""
    state = load_email_state(data_dir)
    state.mark_triaged(email_id)
    save_email_state(state, data_dir)


def run_agentic_email_triage(
    data_dir: Path,
    email_id: str | None = None,
    candidate: EmailTriageCandidate | None = None,
    client: MicrosoftGraphClient | None = None,
) -> dict[str, Any]:
    """Execute Tier 2 Agentic Escalation on a complex/ambiguous email.

    Analyzes message body, cross-references collaborators and open tasks,
    invokes Gemini CLI (or MCP agent), and executes triage actions.
    """
    if candidate is None:
        if not email_id:
            raise ValueError("Either candidate or email_id must be provided")
        graph_client = client or MicrosoftGraphClient(data_dir)
        msg = graph_client.get_message(email_id)
        collab_file = fast_path.load_collaborators(data_dir)
        task_file = fast_path.load_tasks(data_dir)
        sender_name = msg.sender.name if msg.sender else None
        sender_email = msg.sender.address if msg.sender else None
        collab = find_matching_collaborator(sender_name, sender_email, collab_file)
        waiting = find_tasks_waiting_on_sender(sender_name, sender_email, collab, task_file)
        candidate = EmailTriageCandidate(
            email=msg,
            collaborator=collab,
            waiting_tasks=[
                {
                    "id": t.id,
                    "short_id": t.id[:4],
                    "description": t.description,
                    "waiting_on": t.waiting_on,
                    "deadline": t.deadline.isoformat() if t.deadline else None,
                }
                for t in waiting
            ],
        )

    email = candidate.email
    body_text = email.clean_text_body()[:2000]
    sender_str = email.sender.display() if email.sender else "unknown"
    collab_str = (
        f"{candidate.collaborator.name} ({candidate.collaborator.role or 'collaborator'})"
        if candidate.collaborator
        else "Unknown"
    )

    waiting_lines = [
        f"- Task [{t['short_id']}] '{t['description']}' (waiting on {t.get('waiting_on')})"
        for t in candidate.waiting_tasks
    ]
    waiting_str = "\n".join(waiting_lines) if waiting_lines else "None"

    prompt = f"""You are Marvin's autonomous email triage agent. An email requires NLU reasoning to resolve tasks and blockers.

Sender: {sender_str}
Matched Collaborator: {collab_str}
Subject: {email.subject}
Message Content:
\"\"\"{body_text}\"\"\"

Open Waiting Tasks:
{waiting_str}

Analyze the email and decide on the best triage action(s).
Output ONLY valid JSON matching this schema:
{{
  "thought": "brief reasoning explaining why this action was chosen",
  "actions": [
    {{
      "type": "unblock_task" | "create_task" | "add_note" | "dismiss",
      "task_id": "task_id_or_prefix",
      "note": "resolution or progress note",
      "description": "new task description",
      "deadline": "YYYY-MM-DD",
      "priority": "high" | "medium" | "low"
    }}
  ]
}}
"""

    if not shutil.which("gemini"):
        return {
            "status": "manual_needed",
            "reason": "gemini_cli_not_found",
            "message": "Gemini CLI not found. Please triage manually via 'marvin email triage'.",
            "email_id": email.id,
            "candidate": candidate.to_dict(),
        }

    try:
        proc = subprocess.run(
            ["gemini", prompt],
            cwd=data_dir,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0:
            return {
                "status": "error",
                "error": f"Gemini CLI exited with code {proc.returncode}: {proc.stderr}",
                "email_id": email.id,
            }

        output = proc.stdout.strip()
        match = re.search(r"\{.*\}", output, re.DOTALL)
        if not match:
            return {
                "status": "error",
                "error": f"Could not parse JSON from Gemini output: {output[:200]}",
                "email_id": email.id,
            }

        parsed = json.loads(match.group(0))
        actions_taken = []

        for act in parsed.get("actions", []):
            act_type = act.get("type")
            if act_type == "unblock_task":
                tid = act.get("task_id")
                if tid:
                    resolve_email_blocker(
                        data_dir,
                        tid,
                        email=email,
                        note=act.get("note"),
                    )
                    actions_taken.append(f"Unblocked task {tid}")
            elif act_type == "create_task":
                created = create_task_from_email(
                    data_dir,
                    email,
                    description=act.get("description"),
                    deadline=act.get("deadline"),
                    priority=act.get("priority"),
                )
                actions_taken.append(f"Created task [{created.id[:4]}] {created.description}")
            elif act_type == "add_note":
                tid = act.get("task_id")
                note_text = act.get("note") or f"Update from email '{email.subject}'"
                if tid:
                    fast_path.add_note(data_dir, tid, note_text)
                    actions_taken.append(f"Added note to task {tid}")
            elif act_type == "dismiss":
                dismiss_email(data_dir, email.id)
                actions_taken.append("Dismissed email")

        return {
            "status": "success",
            "email_id": email.id,
            "thought": parsed.get("thought", ""),
            "actions_taken": actions_taken,
        }

    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "error": "Gemini CLI execution timed out after 60 seconds",
            "email_id": email.id,
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "email_id": email.id,
        }
