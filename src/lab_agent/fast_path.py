"""Fast-path handlers for deterministic commands.

These bypass the LLM and parse task files directly in Python.
"""

from datetime import date
from pathlib import Path

from lab_agent.task_schema import TaskFile, load_task_file, save_task_file
from lab_agent import styles


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
        True if any conference deadlines were auto-cleared (requires git sync).
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
    
    # Auto-clear past-due conference deadlines first
    cleared = clear_past_conference_deadlines(data_dir)
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
    
    # Show conference deadlines box at the top (unless filtering by specific tag)
    if not tag and not waiting:
        conference_box = styles.format_conference_box(tf.tasks)
        if conference_box:
            styles.console.print()
            styles.console.print(conference_box)
    
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
        
        # Skip conference deadline tasks when showing the conference box
        # (they're already displayed in the box). Must have BOTH #conference AND #deadline.
        if not tag and not waiting:
            tags_lower = [t.lower() for t in task.tags]
            is_conference_deadline = (
                "conference" in tags_lower 
                and "deadline" in tags_lower 
                and task.deadline is not None
            )
            if is_conference_deadline:
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
        True if any conference deadlines were auto-cleared (requires git sync).
    """
    from rich.text import Text
    
    # Auto-clear past-due conference deadlines first
    cleared = clear_past_conference_deadlines(data_dir)
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
    
    return bool(cleared)


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
    from lab_agent.task_schema import Task
    
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
    from lab_agent.task_schema import save_task_file
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


def mark_done(data_dir: Path, task_id: str) -> "Task | None":
    """Mark a task as done by ID.
    
    Returns the modified task, or None if not found.
    """
    from lab_agent.task_schema import save_task_file
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
    from lab_agent.task_schema import save_task_file
    
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


def clear_past_conference_deadlines(data_dir: Path) -> list["Task"]:
    """Auto-clear past-due conference deadline tasks.
    
    Conference deadlines (tasks tagged with 'conference' and 'deadline' 
    and having a deadline date) are automatically marked as done when 
    the deadline passes, since there's no action to take after the deadline.
    
    Returns:
        List of tasks that were cleared. Empty list if none.
    """
    from datetime import date
    
    tasks_path = get_tasks_path(data_dir)
    tf = load_tasks(data_dir)
    today_date = date.today()
    cleared_tasks = []
    
    for task in tf.open_tasks:
        # Check if this is a past-due conference deadline (must have BOTH tags)
        tags_lower = [t.lower() for t in task.tags]
        is_conference_deadline = "conference" in tags_lower and "deadline" in tags_lower
        is_past_due = task.deadline is not None and task.deadline < today_date
        
        if is_conference_deadline and is_past_due:
            task.status = "done"
            task.completed_at = today_date
            cleared_tasks.append(task)
    
    if cleared_tasks:
        save_task_file(tf, tasks_path)
    
    return cleared_tasks
