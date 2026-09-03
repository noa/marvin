"""Tests for proactive_engine.py (Knowledge state evaluation & urgency scoring)."""

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from marvin.task_schema import Task, TaskFile, save_task_file
from marvin.collaborator_schema import Collaborator, CollaboratorFile, save_collaborator_file
from marvin.idea_schema import Idea, IdeaFile, save_idea_file
from marvin.daemon_schema import DaemonState, save_daemon_state
from marvin.proactive_engine import (
    _eval_deadlines,
    _eval_blockers,
    _eval_ideas,
    evaluate_knowledge_state,
)


def test_eval_deadlines():
    """Test deadline urgency scoring, overdue detection, and subtask velocity."""
    today = date(2026, 9, 1)
    now = datetime(2026, 9, 1, 10, 0)

    # 1. Overdue task
    t_overdue = Task(
        id="over01",
        description="Submit grant revision",
        deadline=date(2026, 8, 28),  # 4 days overdue
        priority="high",
        status="open",
    )

    # 2. Due today
    t_today = Task(
        id="today1",
        description="Grade midterms",
        deadline=today,
        priority="medium",
        status="open",
    )

    # 3. Due in 3 days with open subtasks
    t_parent = Task(
        id="icml01",
        description="ICML Submission",
        deadline=date(2026, 9, 4),
        priority="high",
        status="open",
    )
    t_sub1 = Task(
        id="sub001",
        description="Run ablations",
        parent_id="icml01",
        waiting_on="Wei",
        status="open",
    )
    t_sub2 = Task(
        id="sub002",
        description="Draft intro",
        parent_id="icml01",
        status="done",
    )

    # 4. Completed task (should be ignored)
    t_done = Task(
        id="done01",
        description="Old task",
        deadline=date(2026, 8, 20),
        status="done",
    )

    tf = TaskFile(
        project="test",
        tasks=[t_overdue, t_today, t_parent, t_sub1, t_sub2, t_done],
    )

    alerts = _eval_deadlines(tf, today, now)

    # Verify overdue alert
    overdue_alerts = [a for a in alerts if a.urgency_tier == "overdue"]
    assert len(overdue_alerts) == 1
    assert overdue_alerts[0].item_id == "over01"
    assert "4 day(s) overdue" in overdue_alerts[0].narrative

    # Verify due today alert
    today_alerts = [a for a in alerts if a.item_id == "today1"]
    assert len(today_alerts) == 1
    assert today_alerts[0].urgency_tier == "due_today"
    assert "due TODAY" in today_alerts[0].narrative

    # Verify parent task with subtask bottleneck
    parent_alerts = [a for a in alerts if a.item_id == "icml01"]
    assert len(parent_alerts) == 1
    assert parent_alerts[0].category == "subtask_bottleneck"
    assert "1 subtasks remaining open" in parent_alerts[0].narrative
    assert "blocked on collaborators" in parent_alerts[0].narrative


def test_eval_blockers_with_waiting_since():
    """Test that waiting_since overrides task creation date for blocker duration."""
    today = date(2026, 9, 10)
    now = datetime(2026, 9, 10, 10, 0)

    c_alice = Collaborator(name="Alice Chen", role="PhD student")  # 4-day threshold
    cf = CollaboratorFile(collaborators=[c_alice])

    # Task created 30 days ago, but only marked waiting 2 days ago -> should NOT trigger (2 < 4)
    t1 = Task(
        id="t001",
        description="Review Alice's draft",
        waiting_on="Alice Chen",
        created_at=date(2026, 8, 11),  # 30 days ago
        waiting_since=date(2026, 9, 8),  # 2 days ago
        status="open",
    )

    tf = TaskFile(project="test", tasks=[t1])
    alerts = _eval_blockers(tf, cf, today, now)
    assert len(alerts) == 0

    # Task marked waiting 5 days ago -> should trigger (5 >= 4)
    t1.waiting_since = date(2026, 9, 5)
    alerts2 = _eval_blockers(tf, cf, today, now)
    assert len(alerts2) == 1
    assert "for 5 days" in alerts2[0].narrative


def test_evaluate_knowledge_state_batch_rate_limiting(tmp_path: Path):
    """Test that batch evaluation does not exceed max_daily_pings for non-critical alerts."""
    now = datetime(2026, 9, 1, 14, 0)
    today = now.date()

    # 5 tasks due in 7 days (non-critical, tier='t_minus_7d')
    tasks = [
        Task(id=f"t{i}", description=f"Task {i}", deadline=today + timedelta(days=7), priority="medium")
        for i in range(5)
    ]
    save_task_file(TaskFile(project="p1", tasks=tasks), tmp_path / "tasks.json")
    save_collaborator_file(CollaboratorFile(), tmp_path / "collaborators.json")
    save_idea_file(IdeaFile(), tmp_path / "ideas.json")

    daemon_state = DaemonState()
    daemon_state.quiet_hours.enabled = False
    daemon_state.rate_limits.max_daily_pings = 2
    save_daemon_state(daemon_state, tmp_path)

    actionable, squelched = evaluate_knowledge_state(tmp_path, now_dt=now, bypass_filters=False)

    # Exactly 2 should be actionable, 3 should be squelched by daily rate limit
    assert len(actionable) == 2
    assert len(squelched) == 3
    for _, reason in squelched:
        assert reason == "daily_rate_limit_reached"


def test_eval_blockers_with_roles():
    """Test waiting-on stagnation with dynamic role thresholds."""
    today = date(2026, 9, 10)
    now = datetime(2026, 9, 10, 10, 0)

    # Collaborators: Alice (Student, 4d threshold), Bob (Professor, 7d threshold)
    c_alice = Collaborator(name="Alice Chen", role="PhD student")
    c_bob = Collaborator(name="Bob Smith", role="Professor")
    cf = CollaboratorFile(collaborators=[c_alice, c_bob])

    # Task waiting on Alice for 5 days -> should trigger (5 >= 4)
    t1 = Task(
        id="t001",
        description="Review Alice's draft",
        waiting_on="Alice Chen",
        created_at=date(2026, 9, 5),  # 5 days ago
        status="open",
    )

    # Task waiting on Bob for 5 days -> should NOT trigger (5 < 7)
    t2 = Task(
        id="t002",
        description="Check equipment quote",
        waiting_on="Bob Smith",
        created_at=date(2026, 9, 5),  # 5 days ago
        status="open",
    )

    # Task waiting on Bob for 8 days -> should trigger (8 >= 7)
    t3 = Task(
        id="t003",
        description="Finalize subaward with Bob",
        waiting_on="Bob Smith",
        created_at=date(2026, 9, 2),  # 8 days ago
        status="open",
    )

    tf = TaskFile(project="test", tasks=[t1, t2, t3])

    alerts = _eval_blockers(tf, cf, today, now)
    alert_ids = [a.item_id for a in alerts]

    assert "t001" in alert_ids  # Alice 5d
    assert "t002" not in alert_ids  # Bob 5d (threshold 7)
    assert "t003" in alert_ids  # Bob 8d


def test_eval_ideas_decay():
    """Test idea garden auto-decay warnings."""
    today = date(2026, 9, 1)
    now = datetime(2026, 9, 1, 10, 0)

    # Idea 1: Spark created 27 days ago (3 days remaining before 30d decay) -> alert!
    i1 = Idea(
        id="idea01",
        thought="Contrastive pretraining for OOD",
        status="spark",
        created_at=date(2026, 8, 5),
        last_tended_at=date(2026, 8, 5),
    )

    # Idea 2: Spark created 10 days ago (20 days remaining) -> no alert
    i2 = Idea(
        id="idea02",
        thought="Diffusion for protein folding",
        status="spark",
        created_at=date(2026, 8, 22),
        last_tended_at=date(2026, 8, 22),
    )

    # Idea 3: Mature idea (does not decay) -> no alert
    i3 = Idea(
        id="idea03",
        thought="Lifelong learning architecture",
        status="mature",
        created_at=date(2026, 5, 1),
    )

    idea_file = IdeaFile(ideas=[i1, i2, i3])
    alerts = _eval_ideas(idea_file, today, now)

    assert len(alerts) == 1
    assert alerts[0].item_id == "idea01"
    assert alerts[0].urgency_tier == "decay_warning"
    assert "auto-decay in 3 days" in alerts[0].narrative


def test_evaluate_knowledge_state_e2e(tmp_path: Path):
    """Test end-to-end knowledge state evaluation and filtering."""
    now = datetime(2026, 9, 1, 14, 0)
    today = now.date()

    # Create task file
    t1 = Task(id="t01", description="Urgent task", deadline=today, priority="high")
    save_task_file(TaskFile(project="p1", tasks=[t1]), tmp_path / "tasks.json")

    # Create empty collaborator and idea files
    save_collaborator_file(CollaboratorFile(), tmp_path / "collaborators.json")
    save_idea_file(IdeaFile(), tmp_path / "ideas.json")

    # Create daemon state with active snooze on t01
    daemon_state = DaemonState()
    daemon_state.quiet_hours.enabled = False
    daemon_state.snooze("t01", now + timedelta(days=1), reason="Meeting tomorrow", now_dt=now)
    save_daemon_state(daemon_state, tmp_path)

    # Standard evaluation: t01 should be squelched because it is snoozed
    actionable, squelched = evaluate_knowledge_state(tmp_path, now_dt=now, bypass_filters=False)
    assert len(actionable) == 0
    assert len(squelched) == 1
    assert squelched[0][0].item_id == "t01"
    assert "snoozed_until" in squelched[0][1]

    # Bypass filters: t01 should become actionable
    actionable_bypass, squelched_bypass = evaluate_knowledge_state(tmp_path, now_dt=now, bypass_filters=True)
    assert len(actionable_bypass) == 1
    assert actionable_bypass[0].item_id == "t01"
