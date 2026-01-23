"""Terminal styling for Lab Agent CLI using Rich."""

from datetime import date
from typing import TYPE_CHECKING

from rich.console import Console
from rich.text import Text
from rich.theme import Theme

if TYPE_CHECKING:
    from lab_agent.task_schema import Task

# Custom theme with lab-agent color palette
LA_THEME = Theme({
    "priority.high": "bold red",
    "priority.medium": "yellow",
    "priority.low": "dim",
    "overdue": "bold red",
    "due.today": "bold yellow",
    "due.soon": "cyan",
    "waiting": "magenta",
    "tag": "bold cyan",
    "project": "bold blue",
    "task.id": "dim cyan",
    "task.done": "dim strike",
    "success": "bold green",
    "error": "bold red",
    "deadline": "yellow",
    "header": "bold blue",
    "divider": "dim blue",
})

# Shared console instance
console = Console(theme=LA_THEME, highlight=False)


def format_priority_badge(priority: str) -> Text:
    """Format priority as a colored badge."""
    if priority == "high":
        return Text(" [HIGH]", style="priority.high")
    elif priority == "low":
        return Text(" [LOW]", style="priority.low")
    return Text("")  # Don't show medium (it's the default)


def format_deadline(deadline: date | None, *, show_relative: bool = True) -> Text:
    """Format deadline with urgency-based coloring."""
    if not deadline:
        return Text("")
    
    today = date.today()
    days_until = (deadline - today).days
    
    # Format the date
    date_str = deadline.strftime("%b %d")
    
    # Add relative time
    if show_relative:
        if days_until < 0:
            rel = f"({abs(days_until)}d late)"
        elif days_until == 0:
            rel = "(today)"
        elif days_until == 1:
            rel = "(tomorrow)"
        else:
            rel = f"({days_until}d)"
        date_str = f"{date_str} {rel}"
    
    # Choose style based on urgency
    if days_until < 0:
        style = "overdue"
        icon = "🔥"
    elif days_until == 0:
        style = "due.today"
        icon = "⚠️"
    elif days_until <= 7:
        style = "due.soon"
        icon = "📅"
    else:
        style = "deadline"
        icon = "📅"
    
    result = Text(f" {icon} ", style=style)
    result.append(date_str, style=style)
    return result


def format_waiting(waiting_on: str | None) -> Text:
    """Format waiting-on badge."""
    if not waiting_on:
        return Text("")
    return Text(f" 👤 {waiting_on}", style="waiting")


def format_tags(tags: list[str]) -> Text:
    """Format tags as bold hashtags."""
    if not tags:
        return Text("")
    
    result = Text(" ")
    for i, tag in enumerate(tags):
        if i > 0:
            result.append(" ")
        result.append(f"#{tag}", style="tag")
    return result


def format_task_id(task_id: str) -> Text:
    """Format the 4-char task ID."""
    return Text(f"{task_id[:4]}", style="task.id")


def format_checkbox(done: bool) -> Text:
    """Format checkbox indicator."""
    if done:
        return Text("☑", style="task.done")
    return Text("☐", style="")


def format_task_rich(
    task: "Task",
    *,
    show_project: str | None = None,
    show_id: bool = True,
    indent: int = 2,
) -> Text:
    """Format a task as a Rich Text object with full styling."""
    result = Text()
    
    # Indentation
    result.append(" " * indent)
    
    # Checkbox
    is_done = task.status == "done"
    result.append_text(format_checkbox(is_done))
    result.append(" ")
    
    # Task ID
    if show_id:
        result.append_text(format_task_id(task.id))
        result.append(" ")
    
    # Description (strike if done)
    if is_done:
        result.append(task.description, style="task.done")
    else:
        result.append(task.description)
    
    # Deadline
    result.append_text(format_deadline(task.deadline))
    
    # Waiting on
    result.append_text(format_waiting(task.waiting_on))
    
    # Priority badge (only for non-medium)
    result.append_text(format_priority_badge(task.priority))
    
    # Tags
    result.append_text(format_tags(task.tags))
    
    return result


def format_project_header(project_name: str) -> Text:
    """Format a project section header."""
    result = Text()
    result.append("━━━ ", style="divider")
    result.append(project_name, style="project")
    result.append(" ━━━", style="divider")
    return result


def format_section_header(title: str, icon: str = "") -> Text:
    """Format a section header for briefings."""
    result = Text()
    if icon:
        result.append(f"{icon} ")
    result.append(title, style="header")
    return result


def print_success(message: str) -> None:
    """Print a success message."""
    console.print(f"[success]✓[/success] {message}")


def print_error(message: str) -> None:
    """Print an error message."""
    console.print(f"[error]✗[/error] {message}", style="error")


def print_warning(message: str) -> None:
    """Print a warning message."""
    console.print(f"[yellow]⚠[/yellow] {message}")
