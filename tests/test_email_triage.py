"""Tests for email triage engine connecting inbox to Marvin tasks and collaborators."""

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from marvin import fast_path
from marvin.collaborator_schema import Collaborator, CollaboratorFile, save_collaborator_file
from marvin.email_schema import EmailAddress, EmailMessage, load_email_state
from marvin.email_triage import (
    create_idea_from_email,
    create_task_from_email,
    dismiss_email,
    find_matching_collaborator,
    find_tasks_waiting_on_sender,
    get_triage_candidates,
    resolve_email_blocker,
)
from marvin.idea_schema import IdeaFile, save_idea_file
from marvin.task_schema import Task, TaskFile, save_task_file


@pytest.fixture
def populated_dir(tmp_path: Path) -> Path:
    tf = TaskFile(
        project="default",
        tasks=[
            Task(id="task1", description="Review ablation experiments", waiting_on="Alice Chen"),
            Task(id="task2", description="Send contract to Bob", waiting_on="Bob"),
            Task(id="task3", description="Prepare NSF slides", deadline=date.today()),
        ],
    )
    save_task_file(tf, tmp_path / "tasks.json")

    cf = CollaboratorFile(
        collaborators=[
            Collaborator(
                id="collab1",
                name="Alice Chen",
                role="PhD student",
                affiliation="JHU",
                email="alice@jhu.edu",
                aliases=["ali"],
            ),
            Collaborator(
                id="collab2",
                name="Bob Smith",
                role="Co-PI",
                email="bob@stanford.edu",
            ),
        ]
    )
    save_collaborator_file(cf, tmp_path / "collaborators.json")
    save_idea_file(IdeaFile(), tmp_path / "ideas.json")
    return tmp_path


def test_find_matching_collaborator(populated_dir: Path):
    cf = fast_path.load_collaborators(populated_dir)

    # By exact email
    c1 = find_matching_collaborator(None, "alice@jhu.edu", cf)
    assert c1 is not None
    assert c1.name == "Alice Chen"

    # By name
    c2 = find_matching_collaborator("Bob Smith", None, cf)
    assert c2 is not None
    assert c2.name == "Bob Smith"

    # By alias
    c3 = find_matching_collaborator("ali", None, cf)
    assert c3 is not None
    assert c3.name == "Alice Chen"

    # Non-existent
    assert find_matching_collaborator("Charlie", "charlie@mit.edu", cf) is None


def test_find_tasks_waiting_on_sender(populated_dir: Path):
    tf = fast_path.load_tasks(populated_dir)
    cf = fast_path.load_collaborators(populated_dir)
    alice = cf.collaborators[0]

    # Task1 is waiting on Alice Chen
    matched = find_tasks_waiting_on_sender("Alice Chen", "alice@jhu.edu", alice, tf)
    assert len(matched) == 1
    assert matched[0].id == "task1"

    # Task2 is waiting on Bob
    matched_bob = find_tasks_waiting_on_sender("Bob Smith", "bob@stanford.edu", cf.collaborators[1], tf)
    assert len(matched_bob) == 1
    assert matched_bob[0].id == "task2"


def test_get_triage_candidates(populated_dir: Path):
    mock_client = MagicMock()
    mock_client.list_messages.return_value = [
        EmailMessage(
            id="msg-alice",
            subject="Ablation runs completed!",
            sender=EmailAddress(name="Alice Chen", address="alice@jhu.edu"),
            body_preview="I finished the ablation runs for table 2.",
            importance="high",
            is_read=False,
        ),
        EmailMessage(
            id="msg-grant",
            subject="Urgent: grant proposal review deadline",
            sender=EmailAddress(name="NSF Program Manager", address="pm@nsf.gov"),
            body_preview="Please submit review by Friday.",
            importance="normal",
            is_read=False,
        ),
        EmailMessage(
            id="msg-newsletter",
            subject="Campus Weekly Update",
            sender=EmailAddress(name="JHU News", address="news@jhu.edu"),
            body_preview="Events this week...",
            importance="normal",
            is_read=False,
        ),
    ]

    candidates = get_triage_candidates(populated_dir, mock_client, limit=10, unread_only=True)
    assert len(candidates) == 3

    # Candidate 1: Alice Chen -> waiting blocker detected!
    c1 = candidates[0]
    assert c1.email.id == "msg-alice"
    assert c1.collaborator is not None
    assert c1.collaborator.name == "Alice Chen"
    assert len(c1.waiting_tasks) == 1
    assert c1.waiting_tasks[0]["id"] == "task1"
    assert c1.suggested_action == "resolve_blocker"

    # Candidate 2: Grant proposal review -> deadline keyword detected!
    c2 = candidates[1]
    assert c2.email.id == "msg-grant"
    assert len(c2.waiting_tasks) == 0
    assert c2.suggested_action == "create_task"

    # Candidate 3: Newsletter -> standard review
    c3 = candidates[2]
    assert c3.suggested_action == "review"


def test_resolve_email_blocker(populated_dir: Path):
    email = EmailMessage(
        id="email-1",
        subject="Ablation data",
        sender=EmailAddress(name="Alice Chen", address="alice@jhu.edu"),
    )

    task = resolve_email_blocker(populated_dir, "task1", email=email)
    assert task.waiting_on is None
    assert any("Unblocked by email" in n for n in task.notes)

    # Verify email state is updated
    state = load_email_state(populated_dir)
    assert state.is_triaged("email-1")


def test_create_task_from_email(populated_dir: Path):
    email = EmailMessage(
        id="email-review",
        subject="Review PhD dissertation chapter",
        sender=EmailAddress(name="Dean Office", address="dean@jhu.edu"),
        body_preview="Please review the chapter before next Monday.",
        importance="high",
    )

    task = create_task_from_email(
        populated_dir,
        email,
        description="Review chapter",
        deadline="2026-09-10",
        priority="high",
    )
    assert task.description == "Review chapter"
    assert str(task.deadline) == "2026-09-10"
    assert task.priority == "high"
    assert "email" in task.tags
    assert any("dean@jhu.edu" in n for n in task.notes)

    state = load_email_state(populated_dir)
    assert state.is_triaged("email-review")
    assert state.created_tasks["email-review"] == task.id


def test_create_idea_from_email(populated_dir: Path):
    email = EmailMessage(
        id="email-spark",
        subject="Could SSMs replace attention for long video?",
        sender=EmailAddress(name="Bob Smith", address="bob@stanford.edu"),
    )

    idea = create_idea_from_email(populated_dir, email, thought="Use SSMs for video")
    assert idea.thought == "Use SSMs for video"
    assert "email" in idea.tags
    assert "Email from" in (idea.source or "")

    state = load_email_state(populated_dir)
    assert state.is_triaged("email-spark")


def test_dismiss_email(populated_dir: Path):
    dismiss_email(populated_dir, "msg-dismissed")
    state = load_email_state(populated_dir)
    assert state.is_triaged("msg-dismissed")
