"""Terminal styling for Marvin CLI using Rich."""

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, TYPE_CHECKING

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

if TYPE_CHECKING:
    from marvin.task_schema import Task
    from marvin.idea_schema import Idea, IdeaNote

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

# Custom theme with Marvin color palette
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
    "grant.title": "bold green",
    "grant.name": "bold white",
    # Collaborator colours
    "person.name": "bold cyan",
    "person.role": "yellow",
    "person.affil": "dim",
    "person.email": "dim cyan",
    "person.id": "dim",
    "person.alias": "dim magenta",
    # Idea colours
    "idea.thought": "italic",
    "idea.id": "dim green",
    "idea.status.spark": "yellow",
    "idea.status.developing": "cyan",
    "idea.status.mature": "bold green",
    "idea.status.archived": "dim",
    "idea.source": "dim italic",
    "idea.warning": "bold yellow",
    # Email colours
    "email.subject": "bold white",
    "email.from": "cyan",
    "email.date": "dim",
    "email.unread": "bold blue",
    "email.preview": "dim",
    "email.badge": "bold magenta",
    "email.blocker": "bold yellow",
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
    show_id: bool = True,
    indent: int = 2,
    show_all_tags: bool = False,
    is_subtask: bool = False,
    subtask_depth: int = 1,
) -> Text:
    """Format a task as a Rich Text object with full styling.
    
    Args:
        task: The task to format
        show_id: Whether to show the task ID
        indent: Indentation level
        show_all_tags: If True, always show tags (for debugging/raw mode)
        is_subtask: If True, use subtask styling with tree prefix
        subtask_depth: Nesting depth for subtasks (1 = direct child, 2 = grandchild, etc.)
    """
    result = Text()
    
    # Indentation and subtask prefix
    if is_subtask:
        # Subtasks get extra indentation and a tree prefix
        result.append(" " * indent)
        result.append("  " * (subtask_depth - 1))  # Extra indent for deeper nesting
        result.append("↳ ", style="dim")
    else:
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
    
    # Tags (always show in raw mode, otherwise only if present and non-conference)
    if show_all_tags or task.tags:
        result.append_text(format_tags(task.tags))
    
    return result


def format_note(text: str, *, indent: int = 2, depth: int = 0) -> Text:
    """Format a note as a dim indented line with a vertical bar prefix.

    Args:
        text: The note text
        indent: Base indentation (matches task indent)
        depth: Nesting depth of the parent task (0 = root)
    """
    result = Text()
    result.append(" " * indent)
    if depth > 0:
        result.append("  " * (depth - 1))
        result.append("  ")  # align with subtask content after "↳ "
    result.append("  ")  # align past checkbox + space
    result.append("│ ", style="dim")
    result.append(text, style="dim")
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
    
    # Filter for open conference deadline tasks (must have BOTH #conference AND #deadline tags)
    conference_tasks = [
        t for t in tasks 
        if t.status == "open" 
        and t.deadline is not None
        and "conference" in [tag.lower() for tag in t.tags]
        and "deadline" in [tag.lower() for tag in t.tags]
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


def format_grant_box(tasks: list["Task"]) -> Panel | None:
    """Format grant deadlines in a visually distinct box.
    
    Args:
        tasks: All tasks (will be filtered for #grant + #deadline)
        
    Returns:
        A Rich Panel containing the grant deadlines, or None if empty
    """
    from datetime import date as date_cls
    
    # Filter for open grant deadline tasks (must have BOTH #grant AND #deadline tags)
    grant_tasks = [
        t for t in tasks 
        if t.status == "open" 
        and t.deadline is not None
        and "grant" in [tag.lower() for tag in t.tags]
        and "deadline" in [tag.lower() for tag in t.tags]
    ]
    
    if not grant_tasks:
        return None
    
    # Sort by deadline
    grant_tasks.sort(key=lambda t: t.deadline)
    
    today = date_cls.today()
    
    # Build lines for the box content
    lines = []
    for task in grant_tasks:
        desc = task.description
        
        # Convert deadline to local time if timezone info is available
        display_date = task.deadline
        time_part = ""
        
        if task.deadline_time:
            converted = convert_deadline_to_local(task.deadline, task.deadline_time)
            if converted:
                display_date, time_part = converted
            else:
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
        line.append(desc, style="grant.name")
        line.append(f" — {date_str}", style="dim")
        if time_part:
            line.append(f" @ {time_part}", style="dim")
        line.append(f" ({rel})", style=style)
        lines.append(line)
    
    content = Group(*lines)
    
    panel = Panel(
        content,
        title="💰 Grant Deadlines",
        title_align="left",
        border_style="green",
        padding=(0, 1),
    )
    
    return panel


# ---------------------------------------------------------------------------
# Collaborator formatting
# ---------------------------------------------------------------------------

def format_collaborator_row(collab: "Collaborator") -> Text:
    """Format a collaborator as a single-line list entry.

    Example:
      👤 ae23  Alice Chen  PhD student · MIT CSAIL  #nlp #student
    """
    from marvin.collaborator_schema import Collaborator  # noqa: F401 (TYPE_CHECKING)

    line = Text("  ")
    line.append("👤 ", style="person.name")
    line.append(collab.id[:4], style="person.id")
    line.append("  ")
    line.append(collab.name, style="person.name")

    meta_parts = []
    if collab.role:
        meta_parts.append(collab.role)
    if collab.affiliation:
        meta_parts.append(collab.affiliation)
    if meta_parts:
        line.append("  ")
        line.append(" · ".join(meta_parts), style="person.affil")

    if collab.email:
        line.append(f"  <{collab.email}>", style="person.email")

    if collab.tags:
        line.append("  ")
        for i, tag in enumerate(collab.tags):
            if i:
                line.append(" ")
            line.append(f"#{tag}", style="tag")

    # Show aliases beyond the auto-generated ones
    explicit_aliases = [a for a in collab.aliases]
    if explicit_aliases:
        line.append("  ")
        line.append("(", style="person.alias")
        line.append(", ".join(explicit_aliases), style="person.alias")
        line.append(")", style="person.alias")

    return line


def format_person_card(
    collab: "Collaborator",
    tasks: list["Task"],
    ideas: list["Idea"] | None = None,
) -> "Panel":
    """Format a full person card: profile block + related tasks + related ideas.

    Args:
        collab: The collaborator to display
        tasks: Tasks associated with this person (waiting_on matches)
        ideas: Ideas linked to this person (optional)
    """
    from rich.table import Table
    from marvin.collaborator_schema import Collaborator  # noqa: F401

    lines: list[Text | Table] = []

    # --- Profile block ---
    name_line = Text()
    name_line.append(collab.name, style="person.name")
    name_line.append(f"  [{collab.id[:4]}]", style="person.id")
    lines.append(name_line)

    if collab.role or collab.affiliation:
        meta = Text()
        parts = []
        if collab.role:
            parts.append(collab.role)
        if collab.affiliation:
            parts.append(collab.affiliation)
        meta.append(" · ".join(parts), style="person.affil")
        lines.append(meta)

    if collab.email:
        email_line = Text()
        email_line.append(f"✉  {collab.email}", style="person.email")
        lines.append(email_line)

    if collab.tags:
        tag_line = Text()
        for i, tag in enumerate(collab.tags):
            if i:
                tag_line.append(" ")
            tag_line.append(f"#{tag}", style="tag")
        lines.append(tag_line)

    # Aliases (explicit + auto combined, deduped)
    all_aliases = collab.all_aliases()
    if all_aliases:
        alias_line = Text()
        alias_line.append("aliases: ", style="dim")
        alias_line.append(", ".join(all_aliases), style="person.alias")
        lines.append(alias_line)

    # Added date
    date_line = Text()
    date_line.append(f"added {collab.added_at.strftime('%b %d, %Y')}", style="dim")
    lines.append(date_line)

    # --- Notes ---
    if collab.notes:
        lines.append(Text())  # blank line
        notes_header = Text("Notes:", style="header")
        lines.append(notes_header)
        for note in collab.notes:
            note_line = Text()
            note_line.append("  │ ", style="dim")
            note_line.append(note, style="dim")
            lines.append(note_line)

    # --- Related tasks ---
    if tasks:
        lines.append(Text())  # blank line
        tasks_header = Text(f"Waiting-on tasks ({len(tasks)}):", style="header")
        lines.append(tasks_header)
        for task in tasks:
            task_line = Text("  ")
            if task.status == "done":
                task_line.append("☑", style="task.done")
            else:
                task_line.append("☐")
            task_line.append(" ")
            task_line.append(task.id[:4], style="task.id")
            task_line.append(" ")
            if task.status == "done":
                task_line.append(task.description, style="task.done")
            else:
                task_line.append(task.description)
            task_line.append_text(format_deadline(task.deadline))
            lines.append(task_line)
    else:
        lines.append(Text())
        lines.append(Text("No waiting-on tasks.", style="dim"))

    # --- Related ideas ---
    if ideas:
        lines.append(Text())  # blank line
        ideas_header = Text(f"Related ideas ({len(ideas)}):", style="header")
        lines.append(ideas_header)
        for idea in ideas:
            idea_line = Text("  ")
            idea_line.append("💡 ", style="idea.id")
            idea_line.append(idea.id[:4], style="idea.id")
            idea_line.append(" ")
            idea_line.append(idea.thought, style="idea.thought")
            idea_line.append(" ")
            idea_line.append_text(format_idea_status(idea.status))
            lines.append(idea_line)

    content = Group(*lines)
    panel = Panel(
        content,
        title=f"👤 {collab.name}",
        title_align="left",
        border_style="cyan",
        padding=(0, 1),
    )
    return panel


# ---------------------------------------------------------------------------
# Idea formatting
# ---------------------------------------------------------------------------

def format_idea_status(status: str) -> Text:
    """Format idea status as a colored badge."""
    style_map = {
        "spark": "idea.status.spark",
        "developing": "idea.status.developing",
        "mature": "idea.status.mature",
        "promoted": "dim",
        "archived": "idea.status.archived",
    }
    return Text(status, style=style_map.get(status, "dim"))


def format_idea_rich(
    idea: "Idea",
    *,
    show_id: bool = True,
    indent: int = 2,
    show_warning: bool = True,
) -> Text:
    """Format an idea as a Rich Text object.

    Shows:
      💡 ae23  contrastive pretraining for distribution shift  #ml #transfer
               spark · 25d · ⚠️ archiving in 5 days
    """
    # Line 1: icon + id + thought + tags
    result = Text()
    result.append(" " * indent)
    if idea.status == "spark":
        icon_style = "idea.status.spark"
    elif idea.status == "developing":
        icon_style = "idea.status.developing"
    else:
        icon_style = "idea.status.mature"
    result.append("💡 ", style=icon_style)

    if show_id:
        result.append(idea.id[:4], style="idea.id")
        result.append(" ")

    result.append(idea.thought, style="idea.thought")

    if idea.tags:
        result.append_text(format_tags(idea.tags))

    # Line 2: status + age + warning
    meta = Text()
    meta.append(" " * indent)
    if show_id:
        meta.append("      ")  # align under thought (past "💡 ae23 ")
    else:
        meta.append("   ")  # align under thought (past "💡 ")

    meta.append_text(format_idea_status(idea.status))

    # Age
    age_days = (date.today() - idea.created_at).days
    if age_days == 0:
        meta.append(" · today", style="dim")
    elif age_days == 1:
        meta.append(" · 1 day", style="dim")
    else:
        meta.append(f" · {age_days}d", style="dim")

    # Note count
    if idea.notes:
        meta.append(
            f" · {len(idea.notes)} note{'s' if len(idea.notes) != 1 else ''}",
            style="dim",
        )

    # People
    if idea.people:
        meta.append(" · ", style="dim")
        for i, person in enumerate(idea.people):
            if i > 0:
                meta.append(", ", style="dim")
            meta.append(person, style="waiting")

    # Warning indicator
    if show_warning and idea.is_warning():
        remaining = idea.days_until_archive()
        if remaining is not None:
            if remaining == 0:
                meta.append(" · ", style="dim")
                meta.append("⚠️  archiving today", style="idea.warning")
            elif remaining == 1:
                meta.append(" · ", style="dim")
                meta.append("⚠️  archiving tomorrow", style="idea.warning")
            else:
                meta.append(" · ", style="dim")
                meta.append(
                    f"⚠️  archiving in {remaining}d", style="idea.warning"
                )

    # Source
    if idea.source:
        meta.append(f" · {idea.source}", style="idea.source")

    # Combine lines
    result.append("\n")
    result.append_text(meta)

    return result


def format_idea_note(note: "IdeaNote", *, indent: int = 2, extra_indent: int = 0) -> Text:
    """Format an idea note with timestamp.

    Args:
        note: IdeaNote object with text and added_at
        indent: Base indentation
        extra_indent: Additional indent (for alignment)
    """
    result = Text()
    result.append(" " * indent)
    result.append(" " * extra_indent)
    result.append("  │ ", style="dim")
    date_str = note.added_at.strftime("%b %d")
    result.append(f"{date_str}: ", style="dim cyan")
    result.append(note.text, style="dim")
    return result


def format_idea_card(idea: "Idea") -> Panel:
    """Format a full idea detail card.

    Shows all metadata, notes, and links in a Panel.
    """
    lines = []

    # Thought (title)
    thought_line = Text()
    thought_line.append(idea.thought, style="idea.thought")
    thought_line.append(f"  [{idea.id[:4]}]", style="idea.id")
    lines.append(thought_line)

    # Status + age
    status_line = Text()
    status_line.append_text(format_idea_status(idea.status))
    age_days = (date.today() - idea.created_at).days
    status_line.append(
        f" · captured {idea.created_at.strftime('%b %d, %Y')}", style="dim"
    )
    if age_days > 0:
        status_line.append(f" ({age_days}d ago)", style="dim")
    lines.append(status_line)

    # Warning
    if idea.is_warning():
        remaining = idea.days_until_archive()
        if remaining is not None:
            warn_line = Text()
            warn_line.append(
                f"⚠️  Auto-archiving in {remaining} day{'s' if remaining != 1 else ''}",
                style="idea.warning",
            )
            lines.append(warn_line)

    # Source
    if idea.source:
        source_line = Text()
        source_line.append(f"source: {idea.source}", style="idea.source")
        lines.append(source_line)

    # Tags
    if idea.tags:
        tag_line = Text()
        for i, tag in enumerate(idea.tags):
            if i:
                tag_line.append(" ")
            tag_line.append(f"#{tag}", style="tag")
        lines.append(tag_line)

    # People
    if idea.people:
        people_line = Text()
        people_line.append("people: ", style="dim")
        people_line.append(", ".join(idea.people), style="waiting")
        lines.append(people_line)

    # Links
    if idea.links:
        links_line = Text()
        links_line.append("links: ", style="dim")
        links_line.append(", ".join(idea.links), style="dim cyan")
        lines.append(links_line)

    # Related tasks
    if idea.related_task_ids:
        rel_line = Text()
        rel_line.append("related tasks: ", style="dim")
        rel_line.append(
            ", ".join(tid[:4] for tid in idea.related_task_ids), style="task.id"
        )
        lines.append(rel_line)

    # Related ideas
    if idea.related_idea_ids:
        rel_line = Text()
        rel_line.append("related ideas: ", style="dim")
        rel_line.append(
            ", ".join(iid[:4] for iid in idea.related_idea_ids), style="idea.id"
        )
        lines.append(rel_line)

    # Promoted to
    if idea.promoted_to:
        prom_line = Text()
        prom_line.append("promoted to task: ", style="dim")
        prom_line.append(idea.promoted_to[:4], style="task.id")
        lines.append(prom_line)

    # Last tended
    if idea.last_tended_at:
        tend_line = Text()
        tend_line.append(
            f"last tended {idea.last_tended_at.strftime('%b %d, %Y')}", style="dim"
        )
        lines.append(tend_line)

    # Notes
    if idea.notes:
        lines.append(Text())  # blank line
        notes_header = Text(f"Notes ({len(idea.notes)}):", style="header")
        lines.append(notes_header)
        for note in idea.notes:
            lines.append(format_idea_note(note, indent=0, extra_indent=0))

    # Archived info
    if idea.status == "archived" and idea.archived_at:
        lines.append(Text())  # blank line
        arch_line = Text()
        arch_line.append(
            f"archived {idea.archived_at.strftime('%b %d, %Y')}", style="dim"
        )
        if idea.archive_reason:
            arch_line.append(f" ({idea.archive_reason})", style="dim")
        lines.append(arch_line)

    # Choose border colour based on status
    border_colors = {
        "spark": "yellow",
        "developing": "cyan",
        "mature": "green",
        "promoted": "dim",
        "archived": "dim",
    }
    border = border_colors.get(idea.status, "yellow")

    content = Group(*lines)
    return Panel(
        content,
        title="💡 Idea",
        title_align="left",
        border_style=border,
        padding=(0, 1),
    )


def format_idea_brief_section(
    stats: dict,
    expiring_count: int,
    just_archived: int = 0,
) -> Text:
    """Format the ideas section for the daily briefing.

    Args:
        stats: Dict with sparks, developing, mature counts
        expiring_count: Number of ideas in warning window
        just_archived: Number of ideas just auto-archived
    """
    result = Text()

    if just_archived > 0:
        result.append(
            f"  Archived {just_archived} untended idea{'s' if just_archived != 1 else ''}\n",
            style="dim",
        )

    if expiring_count > 0:
        result.append(
            f"  {expiring_count} idea{'s' if expiring_count != 1 else ''} expiring soon",
            style="idea.warning",
        )
        result.append(" — run ", style="dim")
        result.append("'marvin ideas tend'", style="dim cyan")
        result.append("\n")

    total = (
        stats.get("sparks", 0) + stats.get("developing", 0) + stats.get("mature", 0)
    )
    if total > 0:
        parts = []
        if stats.get("sparks", 0):
            parts.append(
                f"{stats['sparks']} spark{'s' if stats['sparks'] != 1 else ''}"
            )
        if stats.get("developing", 0):
            parts.append(f"{stats['developing']} developing")
        if stats.get("mature", 0):
            parts.append(f"{stats['mature']} mature")
        result.append(
            f"  {total} active idea{'s' if total != 1 else ''}", style="dim"
        )
        result.append(f" ({', '.join(parts)})\n", style="dim")
    elif just_archived == 0 and expiring_count == 0:
        result.append("  No active ideas\n", style="dim")

    return result


# ---------------------------------------------------------------------------
# Email Formatting Helpers
# ---------------------------------------------------------------------------

def format_email_date(dt: datetime | None) -> str:
    """Format an email datetime into a human-friendly short string."""
    if not dt:
        return ""
    local_dt = dt.astimezone()
    today = date.today()
    if local_dt.date() == today:
        return local_dt.strftime("%-I:%M %p")
    elif local_dt.date() == today - timedelta(days=1):
        return "Yesterday"
    elif local_dt.year == today.year:
        return local_dt.strftime("%b %-d")
    else:
        return local_dt.strftime("%Y-%m-%d")


def format_email_table(candidates: list[Any]) -> Table:
    """Format a list of EmailTriageCandidate or EmailMessage objects as a Rich Table."""
    table = Table(
        show_header=True,
        header_style="bold blue",
        border_style="dim blue",
        box=None,
        padding=(0, 1),
    )
    table.add_column("#", style="dim", justify="right", width=3)
    table.add_column("ID", style="task.id", width=8)
    table.add_column("Date", style="email.date", width=10)
    table.add_column("From", style="email.from", min_width=20, max_width=30, no_wrap=True)
    table.add_column("Subject", style="white", min_width=30, ratio=1)
    table.add_column("Context / Blocker", style="dim", min_width=18)

    for idx, item in enumerate(candidates, 1):
        # Support both EmailTriageCandidate and EmailMessage
        if hasattr(item, "email"):
            msg = item.email
            collab = item.collaborator
            waiting_tasks = item.waiting_tasks
        else:
            msg = item
            collab = None
            waiting_tasks = []

        # From column with collaborator info
        from_text = Text()
        if msg.sender:
            if msg.sender.name and msg.sender.address and msg.sender.name != msg.sender.address:
                from_text.append(f"{msg.sender.name} ", style="email.from")
                from_text.append(f"<{msg.sender.address}>", style="dim")
            else:
                from_text.append(msg.sender.display(), style="email.from")
        else:
            from_text.append("(Unknown)", style="email.from")

        if collab:
            from_text.append(f" [{collab.name}]", style="bold cyan")

        # Subject column with unread indicator
        subj_text = Text()
        if not msg.is_read:
            subj_text.append("● ", style="email.unread")
            subj_text.append(msg.subject, style="bold white")
        else:
            subj_text.append(msg.subject, style="white")

        if msg.importance == "high":
            subj_text.append(" !", style="bold red")
        if msg.has_attachments:
            subj_text.append(" 📎", style="dim")

        # Context / Blocker column
        context_text = Text()
        if waiting_tasks:
            context_text.append(f"⚠️ WAITING ({len(waiting_tasks)})", style="email.blocker")
        elif collab:
            context_text.append(collab.role or "Collaborator", style="dim cyan")
        elif msg.importance == "high":
            context_text.append("HIGH PRIORITY", style="priority.high")

        table.add_row(
            str(idx),
            msg.short_id,
            format_email_date(msg.received_datetime),
            from_text,
            subj_text,
            context_text,
        )

    return table


def format_email_card(candidate: Any) -> Panel:
    """Format a single email triage candidate as a rich card panel."""
    msg = candidate.email if hasattr(candidate, "email") else candidate
    collab = getattr(candidate, "collaborator", None)
    waiting_tasks = getattr(candidate, "waiting_tasks", [])

    body_elements: list[Text] = []

    # Subject header
    subj_line = Text()
    if not msg.is_read:
        subj_line.append("● ", style="email.unread")
    subj_line.append(msg.subject, style="bold white")
    if msg.importance == "high":
        subj_line.append("  [HIGH IMPORTANCE]", style="priority.high")
    body_elements.append(subj_line)

    # Sender & Date line
    meta_line = Text()
    meta_line.append("From: ", style="dim")
    if msg.sender:
        meta_line.append(msg.sender.display(), style="cyan")
    else:
        meta_line.append("(Unknown)", style="dim")

    meta_line.append("   Date: ", style="dim")
    meta_line.append(format_email_date(msg.received_datetime), style="dim")
    body_elements.append(meta_line)

    # Collaborator info
    if collab:
        collab_line = Text()
        collab_line.append("Collaborator: ", style="dim")
        collab_line.append(collab.name, style="bold cyan")
        if collab.role:
            collab_line.append(f" ({collab.role})", style="yellow")
        if collab.affiliation:
            collab_line.append(f" - {collab.affiliation}", style="dim")
        body_elements.append(collab_line)

    # Blocker alerts
    if waiting_tasks:
        blocker_line = Text()
        blocker_line.append("⚠️  You have tasks waiting on this person:", style="email.blocker")
        body_elements.append(blocker_line)
        for t in waiting_tasks:
            t_line = Text()
            t_id = t.get("short_id") or t.get("id", "")[:4]
            t_line.append(f"   • [{t_id}] ", style="task.id")
            t_line.append(t.get("description", ""), style="white")
            if t.get("deadline"):
                t_line.append(f" (due {t['deadline']})", style="yellow")
            body_elements.append(t_line)

    # Body Preview snippet
    preview = msg.body_preview or msg.clean_text_body()[:300]
    if preview:
        body_elements.append(Text())
        body_text = Text()
        body_text.append(preview[:400] + ("..." if len(preview) > 400 else ""), style="dim italic")
        body_elements.append(body_text)

    group = Group(*body_elements)
    border_style = "yellow" if waiting_tasks else "blue"
    return Panel(group, title=f"Email [{msg.short_id}]", border_style=border_style, padding=(1, 2))

