"""Terminal styling for Lab Agent CLI using Rich."""

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING

from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

if TYPE_CHECKING:
    from lab_agent.task_schema import Task

# Timezone offsets in hours from UTC
# Commonly used in academic deadlines
TIMEZONE_OFFSETS: dict[str, int] = {
    # AoE (Anywhere on Earth) = UTC-12
    "AOE": -12,
    # US timezones
    "EST": -5,
    "EDT": -4,
    "CST": -6,
    "CDT": -5,
    "MST": -7,
    "MDT": -6,
    "PST": -8,
    "PDT": -7,
    # European timezones
    "GMT": 0,
    "UTC": 0,
    "BST": 1,
    "CET": 1,
    "CEST": 2,
    # Asian timezones
    "JST": 9,
    "KST": 9,
    "CST_ASIA": 8,  # China Standard Time (use CST_ASIA to avoid conflict)
    "SGT": 8,
    # Australian timezones
    "AEST": 10,
    "AEDT": 11,
}


def convert_deadline_to_local(
    deadline_date: date,
    deadline_time_str: str,
) -> tuple[date, str] | None:
    """Convert a deadline time from its original timezone to local time.
    
    Args:
        deadline_date: The deadline date
        deadline_time_str: Time string like "11:59 PM AoE" or "23:59 UTC"
        
    Returns:
        Tuple of (local_date, local_time_str) or None if parsing fails
    """
    # Parse the time string
    # Patterns: "11:59 PM AoE", "23:59 UTC", "11:59 PM EST", etc.
    time_pattern = r'(\d{1,2}):(\d{2})\s*(AM|PM)?\s*(\w+)?'
    match = re.match(time_pattern, deadline_time_str.strip(), re.IGNORECASE)
    
    if not match:
        return None
    
    hour = int(match.group(1))
    minute = int(match.group(2))
    am_pm = match.group(3)
    tz_str = match.group(4)
    
    # Convert 12-hour to 24-hour if AM/PM present
    if am_pm:
        am_pm = am_pm.upper()
        if am_pm == "PM" and hour != 12:
            hour += 12
        elif am_pm == "AM" and hour == 12:
            hour = 0
    
    # Get source timezone offset
    if tz_str:
        tz_upper = tz_str.upper()
        if tz_upper in TIMEZONE_OFFSETS:
            source_offset_hours = TIMEZONE_OFFSETS[tz_upper]
        else:
            # Try to parse UTC+N or UTC-N format
            utc_match = re.match(r'UTC([+-])(\d+)', tz_upper)
            if utc_match:
                sign = 1 if utc_match.group(1) == '+' else -1
                source_offset_hours = sign * int(utc_match.group(2))
            else:
                return None
    else:
        return None  # No timezone specified
    
    # Create datetime in source timezone
    source_tz = timezone(timedelta(hours=source_offset_hours))
    source_dt = datetime.combine(deadline_date, time(hour, minute), tzinfo=source_tz)
    
    # Convert to local timezone
    local_dt = source_dt.astimezone()
    
    # Format output
    local_time_str = local_dt.strftime("%-I:%M %p").replace(" ", " ")  # e.g., "6:59 AM"
    
    # Get local timezone name
    local_tz_name = local_dt.strftime("%Z")
    if local_tz_name:
        local_time_str = f"{local_time_str} {local_tz_name}"
    
    return local_dt.date(), local_time_str

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
    "conference.title": "bold magenta",
    "conference.name": "bold white",
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


def format_deadline(
    deadline: date | None,
    *,
    deadline_time: str | None = None,
    show_relative: bool = True,
) -> Text:
    """Format deadline with urgency-based coloring.
    
    Times are converted from their original timezone (e.g., AoE) to local time.
    The date displayed reflects the local date of the deadline, which may differ
    from the original date due to timezone conversion.
    
    Args:
        deadline: The deadline date (in original timezone)
        deadline_time: Optional specific time (e.g., "11:59 PM AoE")
        show_relative: Whether to show relative time (e.g., "3d")
    """
    if not deadline:
        return Text("")
    
    # Convert to local time if a timezone-specific time is provided
    display_date = deadline
    local_time_str: str | None = None
    
    if deadline_time:
        converted = convert_deadline_to_local(deadline, deadline_time)
        if converted:
            display_date, local_time_str = converted
        else:
            # Couldn't parse, use original
            local_time_str = deadline_time
    
    today = date.today()
    days_until = (display_date - today).days
    
    # Format the date
    date_str = display_date.strftime("%b %d")
    
    # Add specific time if available
    if local_time_str:
        date_str = f"{date_str} @ {local_time_str}"
    
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
    
    # Deadline (with optional time)
    result.append_text(format_deadline(task.deadline, deadline_time=task.deadline_time))
    
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


def format_conference_box(tasks: list["Task"]) -> Panel | None:
    """Format conference deadlines in a visually distinct box.
    
    Args:
        tasks: List of tasks tagged with 'conference' and having deadlines
        
    Returns:
        A Rich Panel containing the conference deadlines, or None if empty
    """
    from datetime import date as date_cls
    
    # Filter for open conference tasks with deadlines
    conference_tasks = [
        t for t in tasks 
        if t.status == "open" 
        and t.deadline is not None
        and "conference" in [tag.lower() for tag in t.tags]
    ]
    
    if not conference_tasks:
        return None
    
    # Sort by deadline
    conference_tasks.sort(key=lambda t: t.deadline)
    
    today = date_cls.today()
    
    # Build lines for the box content
    lines = []
    for task in conference_tasks:
        desc = task.description
        
        # Convert deadline to local time if timezone info is available
        display_date = task.deadline
        time_part = ""
        
        if task.deadline_time:
            converted = convert_deadline_to_local(task.deadline, task.deadline_time)
            if converted:
                display_date, time_part = converted
            else:
                # Fallback to original time if conversion fails
                time_part = task.deadline_time
        
        days_until = (display_date - today).days
        
        # Format a compact deadline string
        date_str = display_date.strftime("%b %d")
        
        # Urgency indicator and relative time
        if days_until < 0:
            icon = "🔥"
            rel = f"{abs(days_until)}d late"
            style = "overdue"
        elif days_until == 0:
            icon = "⚠️"
            rel = "TODAY"
            style = "due.today"
        elif days_until == 1:
            icon = "📅"
            rel = "tomorrow"
            style = "due.soon"
        elif days_until <= 7:
            icon = "📅"
            rel = f"{days_until}d"
            style = "due.soon"
        else:
            icon = "📅"
            rel = f"{days_until}d"
            style = "deadline"
        
        # Build the line
        line = Text()
        line.append(f"  {icon} ", style=style)
        line.append(desc, style="conference.name")
        line.append(f" — {date_str}", style="dim")
        if time_part:
            line.append(f" @ {time_part}", style="dim")
        line.append(f" ({rel})", style=style)
        lines.append(line)
    
    
    content = Group(*lines)
    
    # Create the panel with a magenta border
    panel = Panel(
        content,
        title="🎓 Conference Deadlines",
        title_align="left",
        border_style="magenta",
        padding=(0, 1),
    )
    
    return panel

