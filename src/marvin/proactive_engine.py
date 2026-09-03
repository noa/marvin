"""Proactive evaluation engine for Always-On Marvin.

Continuously assesses the state of tasks, deadlines, collaborator blockers,
subtask bottlenecks, and idea garden decay. Computes urgency scores and
filters alerts through the daemon state / squelch engine.
"""

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from marvin import fast_path
from marvin.daemon_schema import DaemonState, load_daemon_state, save_daemon_state
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
    item_type: Literal["task", "idea", "collaborator", "email", "general"]
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
        if task.is_overdue(today=today):
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
                tier = "due_today"
                score = 95.0
            elif days_until == 1:
                tier = "due_tomorrow"
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

        ref_date = task.waiting_since or task.created_at
        days_waiting = (today - ref_date).days
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
                    item_type="collaborator",
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
            last_tended = idea.last_tended_at or idea.created_at
            last_tended_str = last_tended.isoformat()

            narrative = (
                f"Your {idea.status} '{idea.thought}' will auto-decay {time_str} "
                f"(last tended: {last_tended_str})."
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


URGENT_ACTION_REGEX = re.compile(
    r"\b(deadline|grant|proposal|review|action required|urgent|subaward|nih|nsf|darpa|award|amendment|contract|budget|compliance)\b",
    re.IGNORECASE,
)
COMPLEX_TOPIC_REGEX = re.compile(
    r"\b(amendment|budget|contract|subaward|compliance|no-cost extension|scheduling)\b",
    re.IGNORECASE,
)


def _eval_emails(
    data_dir: Path,
    today: date,
    now_dt: datetime,
    client: Any | None = None,
) -> tuple[list[ProactiveAlert], int]:
    """Evaluate unread Outlook emails for blocker resolutions and urgent action requests.

    Returns:
        (email_alerts, untriaged_count)
    """
    from marvin.email_schema import load_email_auth

    auth = load_email_auth(data_dir)
    if not auth and client is None:
        return [], 0

    if client is None:
        try:
            import httpx
            from marvin.email_client import MicrosoftGraphClient

            client = MicrosoftGraphClient(data_dir, http_client=httpx.Client(timeout=5.0))
        except Exception:
            return [], 0

    from marvin.email_triage import get_triage_candidates

    try:
        candidates = get_triage_candidates(
            data_dir,
            client,
            limit=15,
            unread_only=True,
            include_triaged=False,
        )
    except Exception:
        return [], 0

    untriaged_count = len(candidates)
    alerts: list[ProactiveAlert] = []

    for candidate in candidates:
        email = candidate.email
        sender_name = (
            candidate.collaborator.name
            if candidate.collaborator
            else (email.sender.name if email.sender else None)
        )
        sender_disp = sender_name or (email.sender.address if email.sender else "Sender")

        # 1. Blocker Reply
        if candidate.waiting_tasks:
            is_complex = (
                len(candidate.waiting_tasks) > 1
                or bool(COMPLEX_TOPIC_REGEX.search(email.subject or ""))
                or bool(COMPLEX_TOPIC_REGEX.search(email.body_preview or ""))
            )

            if is_complex or len(candidate.waiting_tasks) > 1:
                # Ambiguous / Complex Blocker -> Tier 2 Escalation Candidate
                task_count = len(candidate.waiting_tasks)
                desc_list = ", ".join(f"'{t['description'][:25]}'" for t in candidate.waiting_tasks[:2])
                narrative = (
                    f"{sender_disp} replied with '{email.subject}', which could relate to {task_count} waiting tasks ({desc_list}). "
                    f"Agent reasoning recommended to triage and unblock."
                )
                actions = [
                    ProactiveAction(
                        label="Agent Triage",
                        action_type="agent_triage",
                        payload={"email_id": email.id},
                    ),
                    ProactiveAction(
                        label="Manual Triage",
                        action_type="email_triage",
                        payload={"email_id": email.id},
                    ),
                    ProactiveAction(
                        label="Snooze 24h",
                        action_type="snooze",
                        payload={"item_id": email.id, "hours": 24},
                    ),
                ]
                alerts.append(
                    ProactiveAlert(
                        id=f"alert_complex_email_{email.id}",
                        item_id=email.id,
                        item_type="email",
                        title=f"Triage Needed: {sender_disp} ({email.subject[:30]})",
                        narrative=narrative,
                        urgency_tier="ambiguous_blocker_reply",
                        urgency_score=88.0,
                        category="triage",
                        actions=actions,
                        created_at=now_dt,
                    )
                )
            else:
                # Simple Blocker Resolution (Single task match)
                task_info = candidate.waiting_tasks[0]
                task_id = task_info["id"]
                task_short = task_info["short_id"]
                task_desc = task_info["description"]
                score = 85.0
                if task_info.get("priority") == "high" or email.importance == "high":
                    score = 95.0

                urgency_tier = "urgent_blocker_reply" if score >= 90.0 else "blocker_reply"
                narrative = (
                    f"Email from {sender_disp} ('{email.subject}') may resolve blocker on task: '{task_desc}'."
                )
                actions = [
                    ProactiveAction(
                        label=f"Unblock Task {task_short}",
                        action_type="unblock",
                        payload={"task_id": task_id, "email_id": email.id},
                    ),
                    ProactiveAction(
                        label="Add Note",
                        action_type="note",
                        payload={"task_id": task_id},
                    ),
                    ProactiveAction(
                        label="Snooze 24h",
                        action_type="snooze",
                        payload={"item_id": task_id, "hours": 24},
                    ),
                ]
                alerts.append(
                    ProactiveAlert(
                        id=f"alert_email_blocker_{email.id}_{task_short}",
                        item_id=task_id,
                        item_type="task",
                        title=f"{sender_disp} replied: {email.subject[:35]}",
                        narrative=narrative,
                        urgency_tier=urgency_tier,
                        urgency_score=score,
                        category="blocker",
                        actions=actions,
                        created_at=now_dt,
                    )
                )

        # 2. Urgent Action Keywords (not an existing blocker, but urgent request)
        elif URGENT_ACTION_REGEX.search(email.subject or "") or (email.importance == "high"):
            score = 75.0
            if email.importance == "high":
                score = 85.0
            urgency_tier = "urgent_email_action"

            narrative = (
                f"High-priority email from {sender_disp}: '{email.subject}'. "
                f"May require task creation or immediate response."
            )
            actions = [
                ProactiveAction(
                    label="Create Task",
                    action_type="create_task",
                    payload={"email_id": email.id},
                ),
                ProactiveAction(
                    label="Agent Triage",
                    action_type="agent_triage",
                    payload={"email_id": email.id},
                ),
                ProactiveAction(
                    label="Dismiss",
                    action_type="dismiss_email",
                    payload={"email_id": email.id},
                ),
                ProactiveAction(
                    label="Snooze 24h",
                    action_type="snooze",
                    payload={"item_id": email.id, "hours": 24},
                ),
            ]
            alerts.append(
                ProactiveAlert(
                    id=f"alert_urgent_email_{email.id}",
                    item_id=email.id,
                    item_type="email",
                    title=f"Action Email: {email.subject[:35]}",
                    narrative=narrative,
                    urgency_tier=urgency_tier,
                    urgency_score=score,
                    category="triage",
                    actions=actions,
                    created_at=now_dt,
                )
            )

    return alerts, untriaged_count


def evaluate_knowledge_state(
    data_dir: Path,
    now_dt: datetime | None = None,
    bypass_filters: bool = False,
    include_email: bool = True,
    email_client: Any | None = None,
) -> tuple[list[ProactiveAlert], list[tuple[ProactiveAlert, str]]]:
    """Assess the state of tasks, collaborators, ideas, and emails.

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

    if include_email:
        email_alerts, untriaged_count = _eval_emails(data_dir, today, now, client=email_client)
        all_raw_alerts.extend(email_alerts)
        daemon_state.untriaged_emails_count = untriaged_count
        try:
            save_daemon_state(daemon_state, data_dir)
        except Exception:
            pass

    # Sort raw alerts by urgency score
    all_raw_alerts.sort(key=lambda a: a.urgency_score, reverse=True)

    actionable_alerts: list[ProactiveAlert] = []
    squelched_alerts: list[tuple[ProactiveAlert, str]] = []

    critical_tiers = (
        "due_today",
        "overdue",
        "t_minus_24h",
        "urgent_deadline",
        "t_minus_2h",
        "urgent_blocker_reply",
    )
    admitted_non_critical = daemon_state.notifications_sent_today

    for alert in all_raw_alerts:
        is_crit = alert.urgency_tier in critical_tiers
        can_ping, reason = daemon_state.can_ping_item(
            item_id=alert.item_id,
            item_type=alert.item_type,
            urgency_tier=alert.urgency_tier,
            now_dt=now,
            bypass_rate_limit=bypass_filters,
        )

        if bypass_filters:
            actionable_alerts.append(alert)
        elif not can_ping:
            squelched_alerts.append((alert, reason))
        elif not is_crit and admitted_non_critical >= daemon_state.rate_limits.max_daily_pings:
            squelched_alerts.append((alert, "daily_rate_limit_reached"))
        else:
            actionable_alerts.append(alert)
            if not is_crit:
                admitted_non_critical += 1

    return actionable_alerts, squelched_alerts
