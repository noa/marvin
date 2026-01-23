"""Fast-path handlers for deterministic commands.

These bypass the LLM and parse task files directly in Python.
"""

from datetime import date
from pathlib import Path

from lab_agent.task_schema import TaskFile, load_task_file
from lab_agent import styles


def load_all_task_files(data_dir: Path) -> list[tuple[str, TaskFile]]:
    """Load all task files from the data directory.
    
    Returns:
        List of (project_name, TaskFile) tuples
    """
    task_files = []
    
    # Load inbox
    inbox_path = data_dir / "inbox.json"
    if inbox_path.exists():
        try:
            task_files.append(("inbox", load_task_file(inbox_path)))
        except Exception:
            pass  # Skip invalid files
    
    # Load project files
    projects_dir = data_dir / "projects"
    if projects_dir.exists():
        for json_file in projects_dir.rglob("tasks.json"):
            try:
                tf = load_task_file(json_file)
                task_files.append((tf.project, tf))
            except Exception:
                pass
    
    return task_files


def list_tasks(
    data_dir: Path,
    *,
    project: str | None = None,
    tag: str | None = None,
    waiting: bool = False,
    overdue: bool = False,
    week: bool = False,
    today: bool = False,
    show_all: bool = False,
) -> None:
    """List tasks with filters (fast path)."""
    task_files = load_all_task_files(data_dir)
    
    if not task_files:
        styles.console.print("[dim]No tasks found.[/dim]")
        return
    
    # Filter by project if specified
    if project:
        task_files = [
            (name, tf) for name, tf in task_files 
            if project.lower() in name.lower()
        ]
    
    today_date = date.today()
    found_any = False
    
    for proj_name, tf in task_files:
        matching_tasks = []
        
        for task in tf.open_tasks:
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
            
            matching_tasks.append(task)
        
        if matching_tasks:
            if not found_any:
                styles.console.print()  # Leading blank line
            found_any = True
            styles.console.print(styles.format_project_header(proj_name))
            for task in matching_tasks:
                styles.console.print(styles.format_task_rich(task, show_project=proj_name))
    
    if not found_any:
        styles.console.print("[dim]No matching tasks.[/dim]")


def show_brief(data_dir: Path, *, waiting_focus: bool = False) -> None:
    """Generate a daily briefing (fast path)."""
    from rich.text import Text
    
    task_files = load_all_task_files(data_dir)
    today_date = date.today()
    
    overdue_items = []
    due_this_week = []
    waiting_items = []
    
    for proj_name, tf in task_files:
        for task in tf.open_tasks:
            if task.is_overdue():
                overdue_items.append((proj_name, task))
            elif task.is_due_within(7):
                due_this_week.append((proj_name, task))
            
            if task.waiting_on:
                waiting_items.append((proj_name, task))
    
    # Header
    styles.console.print()
    header = Text("📋 Daily Brief", style="bold")
    header.append(f" — {today_date.strftime('%A, %B %d')}", style="dim")
    styles.console.print(header)
    styles.console.print()
    
    # Overdue (critical)
    if overdue_items:
        styles.console.print(styles.format_section_header("OVERDUE", "🔥"))
        for proj, task in overdue_items:
            days_late = (today_date - task.deadline).days
            line = Text("  ")
            line.append(f"[{proj}]", style="project")
            line.append(f" {task.description} ", style="overdue")
            line.append(f"({days_late}d late)", style="overdue")
            styles.console.print(line)
        styles.console.print()
    
    # Due this week
    if due_this_week:
        styles.console.print(styles.format_section_header("Due This Week", "📅"))
        for proj, task in due_this_week:
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
            line.append(f"[{proj}]", style="project")
            line.append(f" {task.description} ")
            line.append(f"({when})", style=when_style)
            styles.console.print(line)
        styles.console.print()
    
    # Waiting on
    if waiting_items and (waiting_focus or not overdue_items):
        styles.console.print(styles.format_section_header("Waiting On", "⏳"))
        # Group by person
        by_person: dict[str, list[tuple[str, str]]] = {}
        for proj, task in waiting_items:
            person = task.waiting_on
            if person not in by_person:
                by_person[person] = []
            by_person[person].append((proj, task.description))
        
        for person, items in by_person.items():
            person_line = Text("  ")
            person_line.append(f"{person}", style="waiting")
            person_line.append(f" — {len(items)} item(s)", style="dim")
            styles.console.print(person_line)
            for proj, desc in items[:2]:  # Show max 2 per person
                item_line = Text("    ")
                item_line.append(f"[{proj}]", style="project")
                item_line.append(f" {desc}", style="dim")
                styles.console.print(item_line)
        styles.console.print()
    
    if not overdue_items and not due_this_week and not waiting_items:
        styles.console.print("[green]✨ All clear! No urgent items.[/green]")
        styles.console.print()


def search_tasks(data_dir: Path, query: str) -> None:
    """Search tasks by keyword or tag (fast path)."""
    from rich.text import Text
    
    task_files = load_all_task_files(data_dir)
    query_lower = query.lower()
    
    # Check if query is a tag search (starts with #)
    is_tag_search = query.startswith('#')
    if is_tag_search:
        query_lower = query_lower[1:]  # Remove the #
    
    results = []
    for proj_name, tf in task_files:
        for task in tf.tasks:  # Search all tasks, not just open
            if is_tag_search:
                # Search tags only
                if query_lower in [t.lower() for t in task.tags]:
                    results.append((proj_name, task))
            else:
                # Search description and tags
                if query_lower in task.description.lower():
                    results.append((proj_name, task))
                elif query_lower in [t.lower() for t in task.tags]:
                    results.append((proj_name, task))
    
    if results:
        styles.console.print()
        header = Text(f"Found {len(results)} result(s) for ", style="dim")
        header.append(f"'{query}'", style="bold cyan")
        styles.console.print(header)
        styles.console.print()
        
        for proj, task in results:
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
            # Project
            line.append(f"[{proj}]", style="project")
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
    from lab_agent.task_schema import load_task_file, TaskFile, Task
    
    task_id_lower = task_id.lower()
    
    # Search inbox
    inbox_path = data_dir / "inbox.json"
    if inbox_path.exists():
        try:
            tf = load_task_file(inbox_path)
            for task in tf.tasks:
                if task.id.lower().startswith(task_id_lower):
                    return (inbox_path, tf, task)
        except Exception:
            pass
    
    # Search project files
    projects_dir = data_dir / "projects"
    if projects_dir.exists():
        for json_file in projects_dir.rglob("tasks.json"):
            try:
                tf = load_task_file(json_file)
                for task in tf.tasks:
                    if task.id.lower().startswith(task_id_lower):
                        return (json_file, tf, task)
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

