"""Proactive evaluation engine for Always-On Marvin.

Continuously assesses the state of tasks, deadlines, collaborator blockers,
subtask bottlenecks, and idea garden decay. Computes urgency scores and
filters alerts through the daemon state / squelch engine.
"""

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from marvin import fast_path
from marvin.daemon_schema import DaemonState, load_daemon_state
from marvin.task_schema import Task, TaskFile
from marvin.collaborator_schema import Collaborator, CollaboratorFile
from marvin.idea_schema import Idea, IdeaFile


class ProactiveAction(BaseModel):
    """An actionable option proposed to the user."""

    label: str
    action_type: str  # "done", "snooze", "reschedule", "note", "develop", "unblock"
    payload: dict = Field(default_factory=dict)


class ProactiveAlert(BaseModel):
    """A synthesized proactive alert."""

    id: str
    item_id: str
    item_type: Literal["task", "idea", "collaborator", "general"]
    title: str
    narrative: str
    urgency_tier: str  # e.g., "t_minus_24h", "t_minus_3d", "overdue", "stagnant_wait", "decay_warning"
    urgency_score: float  # 0.0 to 100.0
    category: Literal["deadline", "blocker", "idea_decay", "subtask_bottleneck", "triage"]
    actions: list[ProactiveAction] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)


def _eval_deadlines(
    tf: TaskFile,
    today: date,
    now_dt: datetime,
) -> list[ProactiveAlert]:
    """Evaluate open tasks for deadline proximity, overdue status, and subtask velocity."""
    alerts = []

    for task in tf.open_tasks:
        # Check subtasks status for root tasks
        children = tf.get_children(task.id) if not task.parent_id else []
        open_children = [c for c in children if c.status == "open"]
        blocked_children = [c for c in open_children if c.waiting_on]

        # 1. Overdue Tasks
        if task.is_overdue():
            days_overdue = (today - task.deadline).days
            score = min(100.0, 70.0 + (days_overdue * 4.0))
            if task.priority == "high":
                score = min(100.0, score + 15.0)

            subtask_info = ""
            if open_children:
                subtask_info = f" ({len(open_children)} subtasks still open)"

            narrative = (
                f"Task '{task.description}' is {days_overdue} day(s) overdue "
                f"(was due {task.deadline.isoformat()}){subtask_info}."
            )

            actions = [
                ProactiveAction(label="Mark Done", action_type="done", payload={"task_id": task.id}),
                ProactiveAction(
                    label="Reschedule +3d",
                    action_type="reschedule",
                    payload={"task_id": task.id, "days": 3},
                ),
                ProactiveAction(
                    label="Snooze 24h",
                    action_type="snooze",
                    payload={"item_id": task.id, "hours": 24},
                ),
            ]

            alerts.append(
                ProactiveAlert(
                    id=f"alert_overdue_{task.id}",
                    item_id=task.id,
                    item_type="task",
                    title=f"Overdue ({days_overdue}d): {task.description[:40]}",
                    narrative=narrative,
                    urgency_tier="overdue",
                    urgency_score=score,
                    category="deadline",
                    actions=actions,
                    created_at=now_dt,
                )
            )

        # 2. Upcoming Deadlines
        elif task.deadline is not None and task.deadline >= today:
            days_until = (task.deadline - today).days

            tier = None
            score = 0.0

            if days_until == 0:
                tier = "t_minus_24h"
                score = 90.0
            elif days_until == 1:
                tier = "t_minus_24h"
                score = 80.0
            elif 2 <= days_until <= 3:
                tier = "t_minus_3d"
                score = 65.0
            elif 4 <= days_until <= 7:
                tier = "t_minus_7d"
                score = 48.0
            elif 8 <= days_until <= 14:
                tier = "t_minus_14d"
                score = 30.0

            if tier is not None:
                if task.priority == "high":
                    score = min(100.0, score + 15.0)

                subtask_info = ""
                category: Literal["deadline", "subtask_bottleneck"] = "deadline"
                if open_children:
                    category = "subtask_bottleneck"
                    subtask_info = (
                        f" Bottleneck check: {len(open_children)} subtasks remaining open"
                    )
                    if blocked_children:
                        subtask_info += f" ({len(blocked_children)} blocked on collaborators)"
                    score = min(100.0, score + 10.0)

                if days_until == 0:
                    time_desc = "TODAY"
                elif days_until == 1:
                    time_desc = "TOMORROW"
                else:
                    time_desc = f"in {days_until} days"

                narrative = (
                    f"Task '{task.description}' is due {time_desc} ({task.deadline.isoformat()}).{subtask_info}"
                )

                actions = [
                    ProactiveAction(label="Mark Done", action_type="done", payload={"task_id": task.id}),
                    ProactiveAction(
                        label="Add Note",
                        action_type="note",
                        payload={"task_id": task.id},
                    ),
                    ProactiveAction(
                        label="Snooze 24h",
                        action_type="snooze",
                        payload={"item_id": task.id, "hours": 24},
                    ),
                ]

                alerts.append(
                    ProactiveAlert(
                        id=f"alert_deadline_{task.id}_{tier}",
                        item_id=task.id,
                        item_type="task",
                        title=f"Due {time_desc}: {task.description[:40]}",
                        narrative=narrative,
                        urgency_tier=tier,
                        urgency_score=score,
                        category=category,
                        actions=actions,
                        created_at=now_dt,
                    )
                )

    return alerts


def _eval_blockers(
    tf: TaskFile,
    cf: CollaboratorFile,
    today: date,
    now_dt: datetime,
) -> list[ProactiveAlert]:
    """Evaluate waiting-on tasks for stagnation."""
    alerts = []

    for task in tf.open_tasks:
        if not task.waiting_on:
            continue

        person_query = task.waiting_on
        collab = cf.find_by_query(person_query)

        # Dynamic threshold based on collaborator role
        threshold_days = 7
        role_desc = "collaborator"
        if collab:
            role_lower = (collab.role or "").lower()
            if any(k in role_lower for k in ("student", "phd", "grad", "postdoc", "ra")):
                threshold_days = 4
                role_desc = collab.role or "student"
            elif collab.role:
                role_desc = collab.role

        days_waiting = (today - task.created_at).days
        if days_waiting >= threshold_days:
            score = min(85.0, 50.0 + (days_waiting * 3.0))
            if task.priority == "high":
                score = min(100.0, score + 10.0)

            narrative = (
                f"You've been waiting on {person_query} ({role_desc}) for {days_waiting} days "
                f"on task: '{task.description}'."
            )

            actions = [
                ProactiveAction(
                    label=f"Nudge {person_query}",
                    action_type="nudge",
                    payload={"person": person_query, "task_id": task.id},
                ),
                ProactiveAction(
                    label="Mark Unblocked",
                    action_type="unblock",
                    payload={"task_id": task.id},
                ),
                ProactiveAction(
                    label="Snooze 48h",
                    action_type="snooze",
                    payload={"item_id": task.id, "hours": 48},
                ),
            ]

            alerts.append(
                ProactiveAlert(
                    id=f"alert_blocker_{task.id}_{days_waiting}d",
                    item_id=task.id,
                    item_type="task",
                    title=f"Waiting on {person_query} ({days_waiting}d)",
                    narrative=narrative,
                    urgency_tier="stagnant_wait",
                    urgency_score=score,
                    category="blocker",
                    actions=actions,
                    created_at=now_dt,
                )
            )

    return alerts


def _eval_ideas(
    idea_file: IdeaFile,
    today: date,
    now_dt: datetime,
) -> list[ProactiveAlert]:
    """Evaluate active sparks and developing ideas for approaching auto-decay."""
    alerts = []

    for idea in idea_file.ideas:
        if idea.status in ("archived", "promoted"):
            continue

        days_left = idea.days_until_archive(today)
        if days_left is None:
            continue

        # Alert if <= 5 days remaining before decay
        if days_left <= 5:
            score = max(35.0, 75.0 - (days_left * 8.0))
            time_str = "TODAY" if days_left == 0 else f"in {days_left} days"

            narrative = (
                f"Your {idea.status} '{idea.thought}' will auto-decay {time_str} "
                f"(last tended: {idea.last_tended_at.isoformat()})."
            )

            actions = [
                ProactiveAction(
                    label="Add Note (Tend)",
                    action_type="note",
                    payload={"idea_id": idea.id},
                ),
                ProactiveAction(
                    label="Develop Idea",
                    action_type="develop",
                    payload={"idea_id": idea.id},
                ),
                ProactiveAction(
                    label="Archive",
                    action_type="archive",
                    payload={"idea_id": idea.id},
                ),
                ProactiveAction(
                    label="Snooze 72h",
                    action_type="snooze",
                    payload={"item_id": idea.id, "hours": 72},
                ),
            ]

            alerts.append(
                ProactiveAlert(
                    id=f"alert_idea_decay_{idea.id}",
                    item_id=idea.id,
                    item_type="idea",
                    title=f"Idea Decaying ({days_left}d left): {idea.thought[:35]}",
                    narrative=narrative,
                    urgency_tier="decay_warning",
                    urgency_score=score,
                    category="idea_decay",
                    actions=actions,
                    created_at=now_dt,
                )
            )

    return alerts


def evaluate_knowledge_state(
    data_dir: Path,
    now_dt: datetime | None = None,
    bypass_filters: bool = False,
) -> tuple[list[ProactiveAlert], list[tuple[ProactiveAlert, str]]]:
    """Assess the state of tasks, collaborators, and ideas.

    Returns:
        (actionable_alerts, squelched_alerts_with_reasons)
        Both sorted by urgency_score descending.
    """
    now = now_dt or datetime.now()
    today = now.date()

    tf = fast_path.load_tasks(data_dir)
    cf = fast_path.load_collaborators(data_dir)
    idea_file = fast_path.load_ideas(data_dir)
    daemon_state = load_daemon_state(data_dir)

    all_raw_alerts: list[ProactiveAlert] = []
    all_raw_alerts.extend(_eval_deadlines(tf, today, now))
    all_raw_alerts.extend(_eval_blockers(tf, cf, today, now))
    all_raw_alerts.extend(_eval_ideas(idea_file, today, now))

    # Sort raw alerts by urgency score
    all_raw_alerts.sort(key=lambda a: a.urgency_score, reverse=True)

    actionable_alerts: list[ProactiveAlert] = []
    squelched_alerts: list[tuple[ProactiveAlert, str]] = []

    for alert in all_raw_alerts:
        can_ping, reason = daemon_state.can_ping_item(
            item_id=alert.item_id,
            item_type=alert.item_type,
            urgency_tier=alert.urgency_tier,
            now_dt=now,
            bypass_rate_limit=bypass_filters,
        )

        if can_ping or bypass_filters:
            actionable_alerts.append(alert)
        else:
            squelched_alerts.append((alert, reason))

    return actionable_alerts, squelched_alerts
