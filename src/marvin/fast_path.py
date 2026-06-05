"""Fast-path handlers for deterministic commands.

These bypass the LLM and parse task files directly in Python.
"""

from datetime import date
from pathlib import Path

from marvin.task_schema import TaskFile, load_task_file, save_task_file
from marvin import styles


def get_tasks_path(data_dir: Path) -> Path:
    """Get the path to the single tasks.json file."""
    return data_dir / "tasks.json"


def load_tasks(data_dir: Path) -> TaskFile:
    """Load the task file from the data directory.
    
    Returns:
        TaskFile object (creates empty one if file doesn't exist)
    """
    tasks_path = get_tasks_path(data_dir)
    if tasks_path.exists():
        try:
            return load_task_file(tasks_path)
        except Exception:
            # Return empty task file if loading fails
            return TaskFile(project="default", tasks=[])
    else:
        return TaskFile(project="default", tasks=[])


def print_task_with_subtasks(
    task_file: "TaskFile",
    task: "Task",
    *,
    show_all_tags: bool = False,
    depth: int = 0,
) -> None:
    """Print a task and all its subtasks recursively.
    
    Args:
        task_file: The TaskFile containing all tasks (for looking up children)
        task: The task to print
        show_all_tags: Whether to show all tags
        depth: Current nesting depth (0 = root task)
    """
    is_subtask = depth > 0
    styles.console.print(
        styles.format_task_rich(
            task,
            show_all_tags=show_all_tags,
            is_subtask=is_subtask,
            subtask_depth=depth,
        )
    )
    
    # Print notes beneath the task line
    for note in task.notes:
        styles.console.print(styles.format_note(note, depth=depth))
    
    # Recursively print children
    children = task_file.get_children(task.id)
    # Sort children: open first, then by deadline
    children.sort(key=lambda t: (t.status == "done", t.deadline or date.max))
    
    for child in children:
        print_task_with_subtasks(
            task_file,
            child,
            show_all_tags=show_all_tags,
            depth=depth + 1,
        )


def list_tasks(
    data_dir: Path,
    *,
    tag: str | None = None,
    waiting: bool = False,
    overdue: bool = False,
    week: bool = False,
    today: bool = False,
    show_all: bool = False,
    raw: bool = False,
) -> bool:
    """List tasks with filters (fast path).
    
    Returns:
        True if any deadline tasks were auto-cleared (caller handles persistence).
    """
    # Raw mode: show all open tasks with full metadata (no filtering, no conference box)
    if raw:
        tf = load_tasks(data_dir)
        styles.console.print()
        styles.console.print("[bold]All open tasks (raw view):[/bold]")
        styles.console.print()
        if tf.open_tasks:
            for task in tf.open_tasks:
                styles.console.print(styles.format_task_rich(task, show_all_tags=True))
        else:
            styles.console.print("[dim]No open tasks.[/dim]")
        return False  # No auto-clearing in raw mode
    
    # Auto-clear past-due conference/grant deadlines first
    cleared = clear_past_deadline_tasks(data_dir)
    if cleared:
        today_date = date.today()
        for task in cleared:
            days_past = (today_date - task.deadline).days
            styles.console.print(
                f"[dim]Auto-cleared past deadline: {task.description} ({days_past}d past)[/dim]"
            )
        styles.console.print()  # Blank line after auto-clear messages
    
    tf = load_tasks(data_dir)
    
    if not tf.tasks:
        styles.console.print("[dim]No tasks found.[/dim]")
        return bool(cleared)
    
    today_date = date.today()
    
    # Show deadline boxes at the top (unless filtering by specific tag)
    if not tag and not waiting:
        conference_box = styles.format_conference_box(tf.tasks)
        if conference_box:
            styles.console.print()
            styles.console.print(conference_box)
        
        grant_box = styles.format_grant_box(tf.tasks)
        if grant_box:
            styles.console.print()
            styles.console.print(grant_box)
    
    # Filter root-level tasks (subtasks shown under parents)
    matching_tasks = []
    
    for task in tf.get_open_root_tasks():
        # Apply filters
        if waiting and not task.waiting_on:
            continue
        if overdue and not task.is_overdue():
            continue
        if today and (not task.deadline or task.deadline != today_date):
            continue
        if week and not task.is_due_within(7):
            continue
        if tag and tag.lower() not in [t.lower() for t in task.tags]:
            continue
        
        # Skip tasks already displayed in deadline boxes.
        # Must have BOTH #<type> AND #deadline tags with a deadline date.
        if not tag and not waiting:
            tags_lower = [t.lower() for t in task.tags]
            has_deadline_tag = "deadline" in tags_lower and task.deadline is not None
            in_conference_box = has_deadline_tag and "conference" in tags_lower
            in_grant_box = has_deadline_tag and "grant" in tags_lower
            if in_conference_box or in_grant_box:
                continue
        
        matching_tasks.append(task)
    
    if matching_tasks:
        styles.console.print()  # Leading blank line
        for task in matching_tasks:
            # Print task with any subtasks it has
            print_task_with_subtasks(tf, task)
    else:
        styles.console.print("[dim]No matching tasks.[/dim]")
    
    return bool(cleared)


def show_brief(data_dir: Path, *, waiting_focus: bool = False) -> bool:
    """Generate a daily briefing (fast path).
    
    Returns:
        True if any deadline tasks were auto-cleared (caller handles persistence).
    """
    from rich.text import Text
    
    # Auto-clear past-due conference/grant deadlines first
    cleared = clear_past_deadline_tasks(data_dir)
    if cleared:
        today_date = date.today()
        for task in cleared:
            days_past = (today_date - task.deadline).days
            styles.console.print(
                f"[dim]Auto-cleared past deadline: {task.description} ({days_past}d past)[/dim]"
            )
        styles.console.print()  # Blank line after auto-clear messages
    
    tf = load_tasks(data_dir)
    today_date = date.today()
    
    overdue_items = []
    due_this_week = []
    waiting_items = []
    
    for task in tf.open_tasks:
        if task.is_overdue():
            overdue_items.append(task)
        elif task.is_due_within(7):
            due_this_week.append(task)
        
        if task.waiting_on:
            waiting_items.append(task)
    
    # Header
    styles.console.print()
    header = Text("📋 Daily Brief", style="bold")
    header.append(f" — {today_date.strftime('%A, %B %d')}", style="dim")
    styles.console.print(header)
    styles.console.print()
    
    # Overdue (critical)
    if overdue_items:
        styles.console.print(styles.format_section_header("OVERDUE", "🔥"))
        for task in overdue_items:
            days_late = (today_date - task.deadline).days
            line = Text("  ")
            line.append(f"{task.description} ", style="overdue")
            line.append(f"({days_late}d late)", style="overdue")
            styles.console.print(line)
        styles.console.print()
    
    # Due this week
    if due_this_week:
        styles.console.print(styles.format_section_header("Due This Week", "📅"))
        for task in due_this_week:
            days_until = (task.deadline - today_date).days
            if days_until == 0:
                when = "today"
                when_style = "due.today"
            elif days_until == 1:
                when = "tomorrow"
                when_style = "due.today"
            else:
                when = f"in {days_until}d"
                when_style = "due.soon"
            
            line = Text("  ")
            line.append(f"{task.description} ")
            line.append(f"({when})", style=when_style)
            styles.console.print(line)
        styles.console.print()
    
    # Waiting on
    if waiting_items and (waiting_focus or not overdue_items):
        styles.console.print(styles.format_section_header("Waiting On", "⏳"))
        # Group by person
        by_person: dict[str, list[str]] = {}
        for task in waiting_items:
            person = task.waiting_on
            if person not in by_person:
                by_person[person] = []
            by_person[person].append(task.description)
        
        for person, items in by_person.items():
            person_line = Text("  ")
            person_line.append(f"{person}", style="waiting")
            person_line.append(f" — {len(items)} item(s)", style="dim")
            styles.console.print(person_line)
            for desc in items[:2]:  # Show max 2 per person
                item_line = Text("    ")
                item_line.append(f"{desc}", style="dim")
                styles.console.print(item_line)
        styles.console.print()
    
    if not overdue_items and not due_this_week and not waiting_items:
        styles.console.print("[green]✨ All clear! No urgent items.[/green]")
        styles.console.print()
    
    # Ideas section
    just_archived_ideas, warning_ideas = run_idea_decay(data_dir)
    idea_stats = get_idea_stats(data_dir)
    total_active = idea_stats.get("sparks", 0) + idea_stats.get("developing", 0) + idea_stats.get("mature", 0)
    
    if total_active > 0 or just_archived_ideas or warning_ideas:
        styles.console.print(styles.format_section_header("Ideas", "🌱"))
        styles.console.print(styles.format_idea_brief_section(
            idea_stats,
            expiring_count=len(warning_ideas),
            just_archived=len(just_archived_ideas),
        ))
    
    return bool(cleared) or bool(just_archived_ideas)


def search_tasks(data_dir: Path, query: str) -> None:
    """Search tasks by keyword or tag (fast path)."""
    from rich.text import Text
    
    tf = load_tasks(data_dir)
    query_lower = query.lower()
    
    # Check if query is a tag search (starts with #)
    is_tag_search = query.startswith('#')
    if is_tag_search:
        query_lower = query_lower[1:]  # Remove the #
    
    results = []
    for task in tf.tasks:  # Search all tasks, not just open
        if is_tag_search:
            # Search tags only
            if query_lower in [t.lower() for t in task.tags]:
                results.append(task)
        else:
            # Search description and tags
            if query_lower in task.description.lower():
                results.append(task)
            elif query_lower in [t.lower() for t in task.tags]:
                results.append(task)
    
    if results:
        styles.console.print()
        header = Text(f"Found {len(results)} result(s) for ", style="dim")
        header.append(f"'{query}'", style="bold cyan")
        styles.console.print(header)
        styles.console.print()
        
        for task in results:
            line = Text("  ")
            # Checkbox
            if task.status == "done":
                line.append("☑", style="task.done")
            else:
                line.append("☐")
            line.append(" ")
            # ID
            line.append(task.id[:4], style="task.id")
            line.append(" ")
            # Description
            if task.status == "done":
                line.append(task.description, style="task.done")
            else:
                line.append(task.description)
            # Tags
            line.append_text(styles.format_tags(task.tags))
            styles.console.print(line)
    else:
        styles.console.print(f"[dim]No tasks matching '{query}'.[/dim]")


def find_task_by_id(
    data_dir: Path,
    task_id: str,
) -> tuple[Path, "TaskFile", "Task"] | None:
    """Find a task by ID prefix.
    
    Args:
        data_dir: Path to data directory
        task_id: Full ID or prefix (e.g., "ae23" or "ae23f1")
        
    Returns:
        Tuple of (file_path, TaskFile, Task) or None if not found
    """
    from marvin.task_schema import Task
    
    tasks_path = get_tasks_path(data_dir)
    if not tasks_path.exists():
        return None
    
    task_id_lower = task_id.lower()
    
    try:
        tf = load_task_file(tasks_path)
        for task in tf.tasks:
            if task.id.lower().startswith(task_id_lower):
                return (tasks_path, tf, task)
    except Exception:
        pass
    
    return None


def edit_task(
    data_dir: Path,
    task_id: str,
    *,
    add_tags: list[str] | None = None,
    remove_tags: list[str] | None = None,
    set_deadline: str | None = None,
    clear_deadline: bool = False,
    set_priority: str | None = None,
    set_waiting: str | None = None,
    clear_waiting: bool = False,
    set_description: str | None = None,
) -> "Task | None":
    """Edit a task by ID.
    
    Returns the modified task, or None if not found.
    """
    from marvin.task_schema import save_task_file
    from datetime import date
    
    result = find_task_by_id(data_dir, task_id)
    if result is None:
        return None
    
    file_path, task_file, task = result
    
    # Apply edits
    if add_tags:
        for tag in add_tags:
            if tag.startswith('#'):
                tag = tag[1:]
            if tag.lower() not in [t.lower() for t in task.tags]:
                task.tags.append(tag.lower())
    
    if remove_tags:
        for tag in remove_tags:
            if tag.startswith('#'):
                tag = tag[1:]
            task.tags = [t for t in task.tags if t.lower() != tag.lower()]
    
    if set_deadline:
        task.deadline = date.fromisoformat(set_deadline)
    
    if clear_deadline:
        task.deadline = None
    
    if set_priority:
        task.priority = set_priority
    
    if set_waiting:
        task.waiting_on = set_waiting
    
    if clear_waiting:
        task.waiting_on = None
    
    if set_description:
        task.description = set_description
    
    # Save changes
    save_task_file(task_file, file_path)
    
    return task


def add_note(data_dir: Path, task_id: str, text: str) -> "Task | None":
    """Add a note to a task by ID.

    Returns the modified task, or None if not found.
    """
    from marvin.task_schema import save_task_file

    result = find_task_by_id(data_dir, task_id)
    if result is None:
        return None

    file_path, task_file, task = result
    task.notes.append(text)
    save_task_file(task_file, file_path)
    return task


def mark_done(data_dir: Path, task_id: str) -> "Task | None":
    """Mark a task as done by ID.
    
    Returns the modified task, or None if not found.
    """
    from marvin.task_schema import save_task_file
    from datetime import date
    
    result = find_task_by_id(data_dir, task_id)
    if result is None:
        return None
    
    file_path, task_file, task = result
    
    task.status = "done"
    task.completed_at = date.today()
    
    save_task_file(task_file, file_path)
    
    return task


def remove_task(data_dir: Path, task_id: str) -> "Task | None":
    """Remove a task entirely by ID.
    
    Returns the removed task, or None if not found.
    """
    from marvin.task_schema import save_task_file
    
    result = find_task_by_id(data_dir, task_id)
    if result is None:
        return None
    
    file_path, task_file, task = result
    
    # Remove the task from the list
    task_file.tasks = [t for t in task_file.tasks if t.id != task.id]
    
    save_task_file(task_file, file_path)
    
    return task
def clear_overdue_tasks(data_dir: Path) -> list["Task"]:
    """Mark all open overdue tasks as done.
    
    Returns:
        List of tasks that were marked as done.
    """
    from datetime import date
    
    tasks_path = get_tasks_path(data_dir)
    tf = load_tasks(data_dir)
    today_date = date.today()
    cleared_tasks = []
    
    for task in tf.open_tasks:
        if task.is_overdue():
            task.status = "done"
            task.completed_at = today_date
            cleared_tasks.append(task)
    
    if cleared_tasks:
        save_task_file(tf, tasks_path)
            
    return cleared_tasks


def search_tasks_by_query(data_dir: Path, query: str) -> list["Task"]:
    """Find all open tasks matching a free-text query.

    Matches against description and tags (case-insensitive).

    Returns:
        List of matching open tasks.
    """
    tf = load_tasks(data_dir)
    query_lower = query.lower()
    results = []

    for task in tf.open_tasks:
        if query_lower in task.description.lower():
            results.append(task)
        elif query_lower in [t.lower() for t in task.tags]:
            results.append(task)

    return results


def remove_tasks_batch(data_dir: Path, task_ids: list[str]) -> list["Task"]:
    """Remove multiple tasks by their IDs (and any orphaned subtasks).

    Returns:
        List of tasks that were removed.
    """
    from marvin.task_schema import save_task_file

    tasks_path = get_tasks_path(data_dir)
    tf = load_tasks(data_dir)
    ids_to_remove = set(task_ids)

    # Also collect children of removed tasks (orphan cleanup)
    def collect_subtree_ids(parent_id: str) -> set[str]:
        child_ids: set[str] = set()
        for task in tf.tasks:
            if task.parent_id == parent_id:
                child_ids.add(task.id)
                child_ids |= collect_subtree_ids(task.id)
        return child_ids

    for tid in list(ids_to_remove):
        ids_to_remove |= collect_subtree_ids(tid)

    removed = [t for t in tf.tasks if t.id in ids_to_remove]
    tf.tasks = [t for t in tf.tasks if t.id not in ids_to_remove]

    if removed:
        save_task_file(tf, tasks_path)

    return removed


def clear_past_deadline_tasks(data_dir: Path) -> list["Task"]:
    """Auto-clear past-due conference and grant deadline tasks.
    
    Tasks tagged with (#conference OR #grant) AND #deadline that have
    a deadline date are automatically marked as done when the deadline
    passes, since there's no action to take after the deadline.
    
    Returns:
        List of tasks that were cleared. Empty list if none.
    """
    from datetime import date
    
    tasks_path = get_tasks_path(data_dir)
    tf = load_tasks(data_dir)
    today_date = date.today()
    cleared_tasks = []
    
    for task in tf.open_tasks:
        tags_lower = [t.lower() for t in task.tags]
        has_deadline_tag = "deadline" in tags_lower
        is_boxed = "conference" in tags_lower or "grant" in tags_lower
        is_past_due = task.deadline is not None and task.deadline < today_date
        
        if has_deadline_tag and is_boxed and is_past_due:
            task.status = "done"
            task.completed_at = today_date
            cleared_tasks.append(task)
    
    if cleared_tasks:
        save_task_file(tf, tasks_path)
    
    return cleared_tasks


# ---------------------------------------------------------------------------
# Collaborator fast-path functions
# ---------------------------------------------------------------------------

def get_collaborators_path(data_dir: Path) -> Path:
    """Get the path to collaborators.json."""
    return data_dir / "collaborators.json"


def load_collaborators(data_dir: Path) -> "CollaboratorFile":
    """Load collaborators from the data directory."""
    from marvin.collaborator_schema import load_collaborator_file
    return load_collaborator_file(get_collaborators_path(data_dir))


def save_collaborators(data_dir: Path, cf: "CollaboratorFile") -> None:
    """Save collaborators to the data directory."""
    from marvin.collaborator_schema import save_collaborator_file
    save_collaborator_file(cf, get_collaborators_path(data_dir))


def add_collaborator(
    data_dir: Path,
    name: str,
    *,
    role: str | None = None,
    affiliation: str | None = None,
    email: str | None = None,
    extra_aliases: list[str] | None = None,
    tags: list[str] | None = None,
) -> "Collaborator":
    """Add a new collaborator. Returns the created Collaborator."""
    from marvin.collaborator_schema import Collaborator

    cf = load_collaborators(data_dir)

    # Check for duplicate name
    for c in cf.collaborators:
        if c.name.lower() == name.lower():
            raise ValueError(f"Collaborator '{name}' already exists (id: {c.id[:4]})")

    collab = Collaborator(
        name=name,
        role=role,
        affiliation=affiliation,
        email=email,
        aliases=extra_aliases or [],
        tags=tags or [],
    )
    cf.collaborators.append(collab)
    save_collaborators(data_dir, cf)
    return collab


def edit_collaborator(
    data_dir: Path,
    query: str,
    *,
    set_name: str | None = None,
    set_role: str | None = None,
    set_affiliation: str | None = None,
    set_email: str | None = None,
    add_aliases: list[str] | None = None,
    remove_aliases: list[str] | None = None,
    add_tags: list[str] | None = None,
    remove_tags: list[str] | None = None,
) -> "Collaborator | None":
    """Edit a collaborator by name/alias/id. Returns updated collaborator or None."""
    cf = load_collaborators(data_dir)
    collab = cf.find_by_query(query)
    if collab is None:
        return None

    if set_name:
        collab.name = set_name
    if set_role is not None:
        collab.role = set_role or None
    if set_affiliation is not None:
        collab.affiliation = set_affiliation or None
    if set_email is not None:
        collab.email = set_email or None
    if add_aliases:
        for alias in add_aliases:
            a = alias.lower().strip()
            if a and a not in collab.aliases:
                collab.aliases.append(a)
    if remove_aliases:
        collab.aliases = [a for a in collab.aliases if a.lower() not in
                          [r.lower() for r in remove_aliases]]
    if add_tags:
        for tag in add_tags:
            t = tag.lower().strip()
            if t and t not in collab.tags:
                collab.tags.append(t)
    if remove_tags:
        collab.tags = [t for t in collab.tags if t.lower() not in
                       [r.lower() for r in remove_tags]]

    save_collaborators(data_dir, cf)
    return collab


def add_collaborator_note(
    data_dir: Path,
    query: str,
    text: str,
) -> "Collaborator | None":
    """Add a note to a collaborator. Returns updated collaborator or None."""
    cf = load_collaborators(data_dir)
    collab = cf.find_by_query(query)
    if collab is None:
        return None
    collab.notes.append(text)
    save_collaborators(data_dir, cf)
    return collab


def remove_collaborator(
    data_dir: Path,
    query: str,
) -> "Collaborator | None":
    """Remove a collaborator by name/alias/id. Returns removed collaborator or None."""
    cf = load_collaborators(data_dir)
    collab = cf.find_by_query(query)
    if collab is None:
        return None
    cf.collaborators = [c for c in cf.collaborators if c.id != collab.id]
    save_collaborators(data_dir, cf)
    return collab


def get_tasks_for_person(
    data_dir: Path,
    collab: "Collaborator",
) -> list["Task"]:
    """Return all open tasks whose waiting_on fuzzy-matches this collaborator.

    Matches on canonical name and all aliases (case-insensitive).
    """
    tf = load_tasks(data_dir)
    aliases = set(a.lower() for a in collab.all_aliases())
    aliases.add(collab.name.lower())

    results = []
    for task in tf.tasks:
        if task.waiting_on and task.waiting_on.lower() in aliases:
            results.append(task)
    return results


def resolve_waiting_on(
    data_dir: Path,
    name: str,
) -> "tuple[str | None, list[Collaborator]]":
    """Resolve a waiting_on name to a collaborator's canonical name.

    Returns:
        (canonical_name, did_you_mean_list)
        - (name, []) if exact match found — canonical_name is their full name
        - (None, [collab, ...]) if ambiguous
        - (None, []) if no match at all (leave name as-is)
    """
    from marvin.collaborator_schema import resolve_person
    cf = load_collaborators(data_dir)
    exact, suggestions = resolve_person(name, cf)
    if exact:
        return exact.name, []
    return None, suggestions


# ---------------------------------------------------------------------------
# Idea functions
# ---------------------------------------------------------------------------

def get_ideas_path(data_dir: Path) -> Path:
    """Get the path to ideas.json."""
    return data_dir / "ideas.json"


def load_ideas(data_dir: Path) -> "IdeaFile":
    """Load ideas from the data directory.

    Returns:
        IdeaFile object (creates empty one if file doesn't exist)
    """
    from marvin.idea_schema import load_idea_file, IdeaFile

    ideas_path = get_ideas_path(data_dir)
    if ideas_path.exists():
        try:
            return load_idea_file(ideas_path)
        except Exception:
            return IdeaFile()
    else:
        return IdeaFile()


def save_ideas(data_dir: Path, idea_file: "IdeaFile") -> None:
    """Save ideas to the data directory."""
    from marvin.idea_schema import save_idea_file

    save_idea_file(idea_file, get_ideas_path(data_dir))


def find_idea_by_id(
    data_dir: Path,
    idea_id: str,
) -> "tuple[Path, IdeaFile, Idea] | None":
    """Find an idea by ID prefix.

    Args:
        data_dir: Path to data directory
        idea_id: Full ID or prefix (e.g., "ae23" or "ae23f1")

    Returns:
        Tuple of (file_path, IdeaFile, Idea) or None if not found
    """
    from marvin.idea_schema import Idea, IdeaFile

    ideas_path = get_ideas_path(data_dir)
    if not ideas_path.exists():
        return None

    idea_id_lower = idea_id.lower()

    try:
        idea_file = load_ideas(data_dir)
        for idea in idea_file.ideas:
            if idea.id.lower().startswith(idea_id_lower):
                return (ideas_path, idea_file, idea)
    except Exception:
        pass

    return None


def add_idea(
    data_dir: Path,
    thought: str,
    *,
    tags: list[str] | None = None,
    source: str | None = None,
    people: list[str] | None = None,
    links: list[str] | None = None,
) -> "Idea":
    """Add a new idea. Returns the created Idea."""
    from marvin.idea_schema import Idea

    idea_file = load_ideas(data_dir)

    clean_tags = []
    if tags:
        for tag in tags:
            t = tag.lstrip("#").lower().strip()
            if t:
                clean_tags.append(t)

    idea = Idea(
        thought=thought,
        tags=clean_tags,
        source=source,
        people=people or [],
        links=links or [],
    )
    idea_file.ideas.append(idea)
    save_ideas(data_dir, idea_file)
    return idea


def add_idea_note(data_dir: Path, idea_id: str, text: str) -> "Idea | None":
    """Add a note to an idea by ID.

    Returns the modified idea, or None if not found.
    """
    result = find_idea_by_id(data_dir, idea_id)
    if result is None:
        return None

    file_path, idea_file, idea = result
    idea.tend(text)
    save_ideas(data_dir, idea_file)
    return idea


def edit_idea(
    data_dir: Path,
    idea_id: str,
    *,
    add_tags: list[str] | None = None,
    remove_tags: list[str] | None = None,
    add_people: list[str] | None = None,
    remove_people: list[str] | None = None,
    add_links: list[str] | None = None,
    set_source: str | None = None,
) -> "Idea | None":
    """Edit an idea by ID.

    Returns the modified idea, or None if not found.
    """
    result = find_idea_by_id(data_dir, idea_id)
    if result is None:
        return None

    file_path, idea_file, idea = result

    # Apply edits
    if add_tags:
        for tag in add_tags:
            if tag.startswith("#"):
                tag = tag[1:]
            if tag.lower() not in [t.lower() for t in idea.tags]:
                idea.tags.append(tag.lower())

    if remove_tags:
        for tag in remove_tags:
            if tag.startswith("#"):
                tag = tag[1:]
            idea.tags = [t for t in idea.tags if t.lower() != tag.lower()]

    if add_people:
        for person in add_people:
            if person.lower() not in [p.lower() for p in idea.people]:
                idea.people.append(person)

    if remove_people:
        for person in remove_people:
            idea.people = [p for p in idea.people if p.lower() != person.lower()]

    if add_links:
        for link in add_links:
            if link not in idea.links:
                idea.links.append(link)

    if set_source is not None:
        idea.source = set_source or None

    # Save changes
    save_ideas(data_dir, idea_file)
    return idea


def develop_idea(data_dir: Path, idea_id: str, note_text: str) -> "Idea | None":
    """Promote an idea from 'spark' to 'developing' status.

    Returns the modified idea, or None if not found or wrong status.
    """
    result = find_idea_by_id(data_dir, idea_id)
    if result is None:
        return None

    file_path, idea_file, idea = result

    if idea.status != "spark":
        return None

    idea.status = "developing"
    idea.tend(note_text)
    save_ideas(data_dir, idea_file)
    return idea


def mature_idea(data_dir: Path, idea_id: str, note_text: str) -> "Idea | None":
    """Promote an idea from 'developing' to 'mature' status.

    Returns the modified idea, or None if not found or wrong status.
    """
    result = find_idea_by_id(data_dir, idea_id)
    if result is None:
        return None

    file_path, idea_file, idea = result

    if idea.status != "developing":
        return None

    idea.status = "mature"
    idea.tend(note_text)
    save_ideas(data_dir, idea_file)
    return idea


def promote_idea(
    data_dir: Path,
    idea_id: str,
    *,
    deadline: date | None = None,
    parent_id: str | None = None,
    waiting: str | None = None,
) -> "tuple[Idea, Task] | None":
    """Promote an idea to a task.

    Creates a new task from the idea and archives it.

    Returns:
        Tuple of (idea, task) or None if not found or already archived/promoted.
    """
    from marvin.task_schema import Task

    result = find_idea_by_id(data_dir, idea_id)
    if result is None:
        return None

    file_path, idea_file, idea = result

    if idea.status not in ("spark", "developing", "mature"):
        return None

    # Create a task from the idea
    task = Task(
        description=idea.thought,
        tags=list(idea.tags),
        deadline=deadline,
        parent_id=parent_id,
        waiting_on=waiting,
    )

    # Load task file, append, save
    tasks_path = get_tasks_path(data_dir)
    tf = load_tasks(data_dir)
    tf.tasks.append(task)
    save_task_file(tf, tasks_path)

    # Archive the idea
    idea.status = "archived"
    idea.promoted_to = task.id
    idea.archived_at = date.today()
    idea.archive_reason = "promoted"
    save_ideas(data_dir, idea_file)

    return (idea, task)


def archive_idea(data_dir: Path, idea_id: str) -> "Idea | None":
    """Archive an idea manually.

    Returns the archived idea, or None if not found.
    """
    result = find_idea_by_id(data_dir, idea_id)
    if result is None:
        return None

    file_path, idea_file, idea = result

    idea.status = "archived"
    idea.archived_at = date.today()
    idea.archive_reason = "manual"
    save_ideas(data_dir, idea_file)
    return idea


def remove_idea(data_dir: Path, idea_id: str) -> "Idea | None":
    """Remove an idea entirely by ID.

    Returns the removed idea, or None if not found.
    """
    result = find_idea_by_id(data_dir, idea_id)
    if result is None:
        return None

    file_path, idea_file, idea = result

    # Remove the idea from the list
    idea_file.ideas = [i for i in idea_file.ideas if i.id != idea.id]

    save_ideas(data_dir, idea_file)
    return idea


def link_idea(
    data_dir: Path,
    idea_id: str,
    *,
    task_id: str | None = None,
    other_idea_id: str | None = None,
    person: str | None = None,
    url: str | None = None,
) -> "Idea | None":
    """Link an idea to a task, another idea, a person, or a URL.

    Returns the modified idea, or None if not found.
    """
    result = find_idea_by_id(data_dir, idea_id)
    if result is None:
        return None

    file_path, idea_file, idea = result

    if task_id:
        task_result = find_task_by_id(data_dir, task_id)
        if task_result is None:
            return None
        _, _, linked_task = task_result
        if linked_task.id not in idea.related_task_ids:
            idea.related_task_ids.append(linked_task.id)

    if other_idea_id:
        other_result = find_idea_by_id(data_dir, other_idea_id)
        if other_result is None:
            return None
        _, _, other_idea = other_result
        if other_idea.id not in idea.related_idea_ids:
            idea.related_idea_ids.append(other_idea.id)

    if person:
        if person.lower() not in [p.lower() for p in idea.people]:
            idea.people.append(person)

    if url:
        if url not in idea.links:
            idea.links.append(url)

    save_ideas(data_dir, idea_file)
    return idea


def search_ideas(data_dir: Path, query: str) -> None:
    """Search ideas by keyword or tag and print formatted results."""
    from rich.text import Text

    idea_file = load_ideas(data_dir)
    query_lower = query.lower()

    # Check if query is a tag search (starts with #)
    is_tag_search = query.startswith("#")
    if is_tag_search:
        query_lower = query_lower[1:]  # Remove the #

    results = []
    for idea in idea_file.ideas:
        if is_tag_search:
            if query_lower in [t.lower() for t in idea.tags]:
                results.append(idea)
        else:
            if query_lower in idea.thought.lower():
                results.append(idea)
            elif query_lower in [t.lower() for t in idea.tags]:
                results.append(idea)
            elif any(query_lower in n.text.lower() for n in idea.notes):
                results.append(idea)
            elif idea.source and query_lower in idea.source.lower():
                results.append(idea)

    if results:
        styles.console.print()
        header = Text(f"Found {len(results)} idea(s) for ", style="dim")
        header.append(f"'{query}'", style="bold cyan")
        styles.console.print(header)
        styles.console.print()

        for idea in results:
            line = Text("  ")
            # Status indicator
            if idea.status == "archived":
                line.append("◇", style="dim")
            elif idea.is_warning():
                line.append("⚠", style="yellow")
            else:
                line.append("◆")
            line.append(" ")
            # ID
            line.append(idea.id[:4], style="task.id")
            line.append(" ")
            # Thought
            if idea.status == "archived":
                line.append(idea.thought, style="dim")
            else:
                line.append(idea.thought)
            # Status
            line.append(f" [{idea.status}]", style="dim")
            # Tags
            line.append_text(styles.format_tags(idea.tags))
            styles.console.print(line)
    else:
        styles.console.print(f"[dim]No ideas matching '{query}'.[/dim]")


def search_ideas_by_query(data_dir: Path, query: str) -> "list[Idea]":
    """Find all active ideas matching a free-text query.

    Matches against thought, tags, and notes text (case-insensitive).

    Returns:
        List of matching active ideas.
    """
    idea_file = load_ideas(data_dir)
    query_lower = query.lower()
    results = []

    for idea in idea_file.active_ideas:
        if query_lower in idea.thought.lower():
            results.append(idea)
        elif query_lower in [t.lower() for t in idea.tags]:
            results.append(idea)
        elif any(query_lower in n.text.lower() for n in idea.notes):
            results.append(idea)

    return results


def run_idea_decay(data_dir: Path) -> "tuple[list[Idea], list[Idea]]":
    """Run the idea decay process.

    Archives expired ideas and identifies those in warning windows.

    Returns:
        Tuple of (just_archived, warning_ideas).
    """
    idea_file = load_ideas(data_dir)
    today_date = date.today()

    just_archived = []
    for idea in idea_file.active_ideas:
        if idea.is_expired():
            idea.status = "archived"
            idea.archived_at = today_date
            idea.archive_reason = "auto-decay"
            just_archived.append(idea)

    warning_ideas = [
        idea for idea in idea_file.active_ideas
        if idea.is_warning() and idea not in just_archived
    ]

    if just_archived:
        save_ideas(data_dir, idea_file)

    return (just_archived, warning_ideas)


def get_ideas_needing_attention(data_dir: Path) -> "list[Idea]":
    """Get ideas that are in their warning window, sorted by urgency.

    Returns:
        List of expiring ideas, most urgent first.
    """
    idea_file = load_ideas(data_dir)
    return idea_file.expiring_ideas()


def get_ideas_for_person(
    data_dir: Path,
    collab: "Collaborator",
) -> "list[Idea]":
    """Return all active ideas that mention this collaborator.

    Matches on canonical name and all aliases (case-insensitive).
    """
    idea_file = load_ideas(data_dir)
    aliases = set(a.lower() for a in collab.all_aliases())
    aliases.add(collab.name.lower())

    results = []
    for idea in idea_file.active_ideas:
        for person in idea.people:
            if person.lower() in aliases:
                results.append(idea)
                break
    return results


def get_idea_stats(data_dir: Path) -> dict:
    """Get summary statistics for ideas.

    Returns:
        Dict with keys: total, sparks, developing, mature, archived,
        expiring_soon.
    """
    idea_file = load_ideas(data_dir)
    return {
        "total": len(idea_file.ideas),
        "sparks": len(idea_file.sparks),
        "developing": len(idea_file.developing_ideas),
        "mature": len(idea_file.mature_ideas),
        "archived": len([i for i in idea_file.ideas if i.status == "archived"]),
        "expiring_soon": len(idea_file.expiring_ideas()),
    }
