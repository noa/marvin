"""
MCP (Model Context Protocol) server for Marvin.

Exposes Marvin's task management capabilities as MCP tools
for AI agents. Install with: pip install -e ".[mcp]"

Usage:
    marvin-mcp                          # stdio transport (default)
    marvin-mcp --data-dir /path/to/data # custom data directory
"""

import json
import os
import sys
from pathlib import Path


def _get_data_dir() -> str:
    """Resolve data directory from env or default."""
    return os.environ.get("MARVIN_DATA_DIR") or os.environ.get("LA_DATA_DIR") or str(Path.home() / ".marvin")


def _rebuild_index(data_dir: Path) -> None:
    """Rebuild the search index after changes."""
    from marvin.index_schema import rebuild_index
    try:
        rebuild_index(data_dir)
    except Exception:
        pass


def _task_to_dict(task) -> dict:
    """Convert a Task object to a JSON-serializable dict."""
    return {
        "id": task.id,
        "short_id": task.id[:4],
        "description": task.description,
        "status": task.status,
        "deadline": task.deadline.isoformat() if task.deadline else None,
        "deadline_time": task.deadline_time,
        "waiting_on": task.waiting_on,
        "priority": task.priority,
        "tags": task.tags,
        "notes": task.notes,
        "parent_id": task.parent_id,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


def _collab_to_dict(collab) -> dict:
    """Convert a Collaborator object to a JSON-serializable dict."""
    return {
        "id": collab.id,
        "short_id": collab.id[:4],
        "name": collab.name,
        "role": collab.role,
        "affiliation": collab.affiliation,
        "email": collab.email,
        "aliases": collab.all_aliases(),
        "notes": collab.notes,
        "tags": collab.tags,
        "added_at": collab.added_at.isoformat() if collab.added_at else None,
    }


def _idea_to_dict(idea) -> dict:
    """Convert an Idea object to a JSON-serializable dict."""
    d = {
        "id": idea.id,
        "short_id": idea.id[:4],
        "thought": idea.thought,
        "status": idea.status,
        "tags": idea.tags,
        "source": idea.source,
        "people": idea.people,
        "links": idea.links,
        "notes": [
            {"text": n.text, "added_at": n.added_at.isoformat()}
            for n in idea.notes
        ],
        "related_task_ids": idea.related_task_ids,
        "related_idea_ids": idea.related_idea_ids,
        "promoted_to": idea.promoted_to,
        "created_at": idea.created_at.isoformat() if idea.created_at else None,
        "last_tended_at": idea.last_tended_at.isoformat() if idea.last_tended_at else None,
        "archived_at": idea.archived_at.isoformat() if idea.archived_at else None,
        "archive_reason": idea.archive_reason,
    }
    # Include decay info for active ideas
    days_left = idea.days_until_archive()
    if days_left is not None:
        d["days_until_archive"] = days_left
        d["is_warning"] = idea.is_warning()
    return d



def main():
    """Entry point for the marvin-mcp command."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print(
            "MCP dependencies not installed. Install with:\n"
            '  pip install -e ".[mcp]"\n',
            file=sys.stderr,
        )
        sys.exit(1)

    from marvin import fast_path
    from marvin import llm_parse
    from marvin.collaborator_schema import resolve_person

    mcp = FastMCP(
        "marvin",
        instructions=(
            "Task management for academic PIs. "
            "Manages tasks, deadlines, collaborators, and waiting-on items."
        ),
    )

    # Allow --data-dir override via argv
    data_dir_str = _get_data_dir()
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--data-dir" and i < len(sys.argv) - 1:
            data_dir_str = sys.argv[i + 1]
            break

    data_dir = Path(data_dir_str).expanduser()

    # ------------------------------------------------------------------
    # Read Tools
    # ------------------------------------------------------------------

    @mcp.tool()
    def list_tasks(
        today: bool = False,
        week: bool = False,
        tag: str | None = None,
        waiting: bool = False,
        overdue: bool = False,
        show_all: bool = False,
    ) -> str:
        """List tasks with filters.

        Returns open tasks matching the given filters. By default
        returns tasks relevant for today (upcoming deadlines, waiting items).

        Args:
            today: Only items due today.
            week: Items due within 7 days.
            tag: Filter by tag (e.g., 'conference', 'grant').
            waiting: Show only tasks waiting on someone.
            overdue: Show only overdue items.
            show_all: Show all open tasks regardless of filters.
        """
        from datetime import date as _date


        tf = fast_path.load_tasks(data_dir)
        today_date = _date.today()

        if tag and tag.startswith("#"):
            tag = tag[1:]

        results = []
        for task in tf.open_tasks:
            # Skip subtasks in top-level list (they appear under parents)
            if task.parent_id and not show_all:
                continue

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

            entry = _task_to_dict(task)

            # Include subtasks inline
            children = tf.get_children(task.id)
            open_children = [c for c in children if c.status == "open"]
            if open_children:
                entry["subtasks"] = [_task_to_dict(c) for c in open_children]

            results.append(entry)

        return json.dumps(
            {
                "total": len(results),
                "tasks": results,
            },
            indent=2,
        )

    @mcp.tool()
    def get_brief(waiting_focus: bool = False) -> str:
        """Generate a daily briefing summary.

        Provides a structured overview of overdue items, tasks due this week,
        and people the user is waiting on.

        Args:
            waiting_focus: Emphasize waiting-on items in the output.
        """
        from datetime import date as _date


        tf = fast_path.load_tasks(data_dir)
        today_date = _date.today()

        overdue_items = []
        due_this_week = []
        waiting_items = []

        for task in tf.open_tasks:
            if task.is_overdue():
                entry = _task_to_dict(task)
                entry["days_overdue"] = (today_date - task.deadline).days
                overdue_items.append(entry)
            elif task.is_due_within(7):
                entry = _task_to_dict(task)
                entry["days_until_due"] = (task.deadline - today_date).days
                due_this_week.append(entry)

            if task.waiting_on:
                waiting_items.append(_task_to_dict(task))

        # Group waiting items by person
        waiting_by_person: dict[str, list[dict]] = {}
        for item in waiting_items:
            person = item["waiting_on"]
            if person not in waiting_by_person:
                waiting_by_person[person] = []
            waiting_by_person[person].append(item)

        return json.dumps(
            {
                "date": today_date.isoformat(),
                "summary": {
                    "overdue_count": len(overdue_items),
                    "due_this_week_count": len(due_this_week),
                    "waiting_count": len(waiting_items),
                    "total_open": tf.open_count,
                },
                "overdue": overdue_items,
                "due_this_week": due_this_week,
                "waiting_by_person": waiting_by_person,
            },
            indent=2,
        )

    @mcp.tool()
    def search_tasks(query: str) -> str:
        """Search across all tasks by keyword or tag.

        Matches against task descriptions and tags (case-insensitive).
        Searches both open and completed tasks.

        Args:
            query: Search term. Prefix with '#' to search tags only.
        """

        tf = fast_path.load_tasks(data_dir)
        query_lower = query.lower()

        is_tag_search = query.startswith("#")
        if is_tag_search:
            query_lower = query_lower[1:]

        results = []
        for task in tf.tasks:
            if is_tag_search:
                if query_lower in [t.lower() for t in task.tags]:
                    results.append(_task_to_dict(task))
            else:
                if query_lower in task.description.lower():
                    results.append(_task_to_dict(task))
                elif query_lower in [t.lower() for t in task.tags]:
                    results.append(_task_to_dict(task))

        return json.dumps(
            {"query": query, "total": len(results), "results": results},
            indent=2,
        )

    @mcp.tool()
    def show_subtasks(task_id: str) -> str:
        """List subtasks of a given task.

        Args:
            task_id: Task ID or 4-character prefix (e.g., 'ae23').
        """

        result = fast_path.find_task_by_id(data_dir, task_id)
        if result is None:
            return json.dumps({"error": f"Task '{task_id}' not found"})

        _, task_file, parent_task = result
        children = task_file.get_children(parent_task.id)

        return json.dumps(
            {
                "parent": _task_to_dict(parent_task),
                "subtasks": [_task_to_dict(c) for c in children],
            },
            indent=2,
        )

    @mcp.tool()
    def list_people() -> str:
        """List all collaborators/people.

        Returns all registered collaborators with their roles,
        affiliations, aliases, and tags.
        """

        cf = fast_path.load_collaborators(data_dir)
        people = [_collab_to_dict(c) for c in cf.collaborators]
        return json.dumps(
            {"total": len(people), "collaborators": people},
            indent=2,
        )

    @mcp.tool()
    def show_person(person: str) -> str:
        """Show a collaborator's profile and their related tasks.

        Args:
            person: Name, alias, or 4-char ID prefix.
        """

        cf = fast_path.load_collaborators(data_dir)
        collab, suggestions = resolve_person(person, cf)

        if collab is None:
            suggestion_names = [s.name for s in suggestions] if suggestions else []
            return json.dumps(
                {
                    "error": f"Collaborator '{person}' not found",
                    "did_you_mean": suggestion_names,
                }
            )

        tasks = fast_path.get_tasks_for_person(data_dir, collab)
        return json.dumps(
            {
                "collaborator": _collab_to_dict(collab),
                "related_tasks": [_task_to_dict(t) for t in tasks],
            },
            indent=2,
        )

    # ------------------------------------------------------------------
    # Write Tools
    # ------------------------------------------------------------------

    @mcp.tool()
    def add_task(
        task: str,
        parent_id: str | None = None,
        no_llm: bool = False,
    ) -> str:
        """Create a new task from natural language.

        The task text is parsed (optionally by LLM) to extract deadlines,
        tags, waiting-on, and priority from natural language.

        Args:
            task: Task description in natural language
                  (e.g., "review Sarah's draft by Friday @waiting(Sarah)").
            parent_id: Parent task ID to create a subtask (optional).
            no_llm: Skip LLM parsing, use regex-only (faster but less accurate).
        """

        try:
            new_task = llm_parse.add_task(
                data_dir,
                task,
                use_llm=not no_llm,
                parent_id=parent_id,
            )
            _rebuild_index(data_dir)
            return json.dumps(
                {"success": True, "task": _task_to_dict(new_task)},
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def edit_task(
        task_id: str,
        description: str | None = None,
        add_tags: list[str] | None = None,
        remove_tags: list[str] | None = None,
        deadline: str | None = None,
        clear_deadline: bool = False,
        priority: str | None = None,
        waiting: str | None = None,
        clear_waiting: bool = False,
    ) -> str:
        """Modify a task's properties.

        Args:
            task_id: Task ID or 4-character prefix.
            description: New description text.
            add_tags: Tags to add (e.g., ['conference', 'urgent']).
            remove_tags: Tags to remove.
            deadline: Set deadline (YYYY-MM-DD format).
            clear_deadline: Remove the deadline.
            priority: Set priority ('high', 'medium', 'low').
            waiting: Set waiting-on person name.
            clear_waiting: Clear the waiting-on field.
        """

        task = fast_path.edit_task(
            data_dir,
            task_id,
            add_tags=add_tags,
            remove_tags=remove_tags,
            set_deadline=deadline,
            clear_deadline=clear_deadline,
            set_priority=priority,
            set_waiting=waiting,
            clear_waiting=clear_waiting,
            set_description=description,
        )

        if task is None:
            return json.dumps({"error": f"Task '{task_id}' not found"})

        _rebuild_index(data_dir)
        return json.dumps(
            {"success": True, "task": _task_to_dict(task)},
            indent=2,
        )

    @mcp.tool()
    def add_note_to_task(task_id: str, text: str) -> str:
        """Add a note to a task.

        Notes appear as indented annotations beneath the task.

        Args:
            task_id: Task ID or 4-character prefix.
            text: Note text to add.
        """

        task = fast_path.add_note(data_dir, task_id, text)
        if task is None:
            return json.dumps({"error": f"Task '{task_id}' not found"})

        _rebuild_index(data_dir)
        return json.dumps(
            {"success": True, "task": _task_to_dict(task)},
            indent=2,
        )

    @mcp.tool()
    def mark_task_done(task_id: str) -> str:
        """Mark a task as completed.

        Args:
            task_id: Task ID or 4-character prefix.
        """

        task = fast_path.mark_done(data_dir, task_id)
        if task is None:
            return json.dumps({"error": f"Task '{task_id}' not found"})

        _rebuild_index(data_dir)
        return json.dumps(
            {"success": True, "task": _task_to_dict(task)},
            indent=2,
        )

    @mcp.tool()
    def remove_task(task_id: str) -> str:
        """Permanently remove a task.

        Use mark_task_done instead if you want to preserve the task
        in history.

        Args:
            task_id: Task ID or 4-character prefix.
        """

        task = fast_path.remove_task(data_dir, task_id)
        if task is None:
            return json.dumps({"error": f"Task '{task_id}' not found"})

        _rebuild_index(data_dir)
        return json.dumps(
            {"success": True, "removed": _task_to_dict(task)},
            indent=2,
        )

    @mcp.tool()
    def clear_overdue_tasks() -> str:
        """Mark all overdue tasks as done.

        Returns the list of tasks that were cleared.
        """

        cleared = fast_path.clear_overdue_tasks(data_dir)
        if cleared:
            _rebuild_index(data_dir)

        return json.dumps(
            {
                "cleared_count": len(cleared),
                "cleared": [_task_to_dict(t) for t in cleared],
            },
            indent=2,
        )

    @mcp.tool()
    def add_person(
        name: str,
        role: str | None = None,
        affiliation: str | None = None,
        email: str | None = None,
        aliases: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """Add a new collaborator/person.

        Auto-generates aliases from the name (first, last).
        Use the aliases parameter for additional shorthand names.

        Args:
            name: Full name (e.g., "Alice Chen").
            role: Role or position (e.g., "PhD student", "collaborator").
            affiliation: Institution (e.g., "MIT CSAIL").
            email: Email address.
            aliases: Additional aliases for quick lookup.
            tags: Searchable labels (e.g., ["student", "nlp"]).
        """

        try:
            collab = fast_path.add_collaborator(
                data_dir,
                name,
                role=role,
                affiliation=affiliation,
                email=email,
                extra_aliases=aliases or [],
                tags=[t.lstrip("#").lower() for t in (tags or [])],
            )
            _rebuild_index(data_dir)
            return json.dumps(
                {"success": True, "collaborator": _collab_to_dict(collab)},
                indent=2,
            )
        except ValueError as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def add_note_to_person(person: str, text: str) -> str:
        """Add a note to a collaborator.

        Args:
            person: Name, alias, or 4-char ID prefix.
            text: Note text to add.
        """

        collab = fast_path.add_collaborator_note(data_dir, person, text)
        if collab is None:
            return json.dumps({"error": f"Collaborator '{person}' not found"})

        _rebuild_index(data_dir)
        return json.dumps(
            {"success": True, "collaborator": _collab_to_dict(collab)},
            indent=2,
        )

    @mcp.tool()
    def remove_person(person: str) -> str:
        """Remove a collaborator record.

        Only removes the collaborator entry; tasks referencing them
        are not affected.

        Args:
            person: Name, alias, or 4-char ID prefix.
        """

        collab = fast_path.remove_collaborator(data_dir, person)
        if collab is None:
            return json.dumps({"error": f"Collaborator '{person}' not found"})

        _rebuild_index(data_dir)
        return json.dumps(
            {"success": True, "removed": _collab_to_dict(collab)},
            indent=2,
        )

    # ------------------------------------------------------------------
    # Idea Read Tools
    # ------------------------------------------------------------------

    @mcp.tool()
    def list_ideas(
        status: str | None = None,
        tag: str | None = None,
        person: str | None = None,
    ) -> str:
        """List ideas with optional filters.

        Returns active ideas (sparks, developing, mature) by default.
        Use status filter to see archived or promoted ideas.

        Args:
            status: Filter by status ('spark', 'developing', 'mature',
                    'archived', 'promoted'). None = all active.
            tag: Filter by tag (e.g., 'ml', 'nlp').
            person: Filter by associated person name.
        """

        idea_file = fast_path.load_ideas(data_dir)

        if tag and tag.startswith("#"):
            tag = tag[1:]

        results = []
        for idea in idea_file.ideas:
            # Status filter
            if status:
                if idea.status != status.lower():
                    continue
            else:
                # Default: active ideas only
                if idea.status in ("archived", "promoted"):
                    continue

            # Tag filter
            if tag and tag.lower() not in [t.lower() for t in idea.tags]:
                continue

            # Person filter
            if person and person.lower() not in [p.lower() for p in idea.people]:
                continue

            results.append(_idea_to_dict(idea))

        return json.dumps(
            {"total": len(results), "ideas": results},
            indent=2,
        )

    @mcp.tool()
    def show_idea(idea_id: str) -> str:
        """Show full details for one idea.

        Args:
            idea_id: Idea ID or 4-character prefix (e.g., 'ae23').
        """

        result = fast_path.find_idea_by_id(data_dir, idea_id)
        if result is None:
            return json.dumps({"error": f"Idea '{idea_id}' not found"})

        _, _, idea = result
        return json.dumps(
            {"idea": _idea_to_dict(idea)},
            indent=2,
        )

    @mcp.tool()
    def search_ideas(query: str) -> str:
        """Search across all ideas including archived.

        Matches against thought text, tags, notes, and source
        (case-insensitive).

        Args:
            query: Search term. Prefix with '#' to search tags only.
        """

        idea_file = fast_path.load_ideas(data_dir)
        query_lower = query.lower()

        is_tag_search = query.startswith("#")
        if is_tag_search:
            query_lower = query_lower[1:]

        results = []
        for idea in idea_file.ideas:
            if is_tag_search:
                if query_lower in [t.lower() for t in idea.tags]:
                    results.append(_idea_to_dict(idea))
            else:
                if query_lower in idea.thought.lower():
                    results.append(_idea_to_dict(idea))
                elif query_lower in [t.lower() for t in idea.tags]:
                    results.append(_idea_to_dict(idea))
                elif any(query_lower in n.text.lower() for n in idea.notes):
                    results.append(_idea_to_dict(idea))
                elif idea.source and query_lower in idea.source.lower():
                    results.append(_idea_to_dict(idea))

        return json.dumps(
            {"query": query, "total": len(results), "results": results},
            indent=2,
        )

    # ------------------------------------------------------------------
    # Idea Write Tools
    # ------------------------------------------------------------------

    @mcp.tool()
    def add_idea(
        thought: str,
        source: str | None = None,
        context: str | None = None,
        tags: list[str] | None = None,
        people: list[str] | None = None,
        links: list[str] | None = None,
    ) -> str:
        """Capture a new research idea.

        Ideas start as 'sparks' and decay (auto-archive) after 30 days
        unless tended. Use add_note_to_idea or develop_idea to reset
        the decay clock.

        Args:
            thought: The core idea in one or two sentences.
            source: Where the idea came from (e.g., 'paper review',
                    'conversation with Alice', 'seminar').
            context: Conversational context to preserve as the first note.
                     Useful for MCP agents to record how the idea arose.
            tags: Categorization tags (e.g., ['ml', 'nlp']).
            people: Associated people (e.g., ['Alice Chen', 'Bob']).
            links: Related URLs or references.
        """

        try:
            idea = fast_path.add_idea(
                data_dir,
                thought,
                source=source,
                tags=tags,
                people=people,
                links=links,
            )

            # Store context as the first note if provided
            if context:
                fast_path.add_idea_note(data_dir, idea.id, f"Context: {context}")
                # Re-fetch the idea to include the note
                result = fast_path.find_idea_by_id(data_dir, idea.id)
                if result:
                    _, _, idea = result

            _rebuild_index(data_dir)
            return json.dumps(
                {"success": True, "idea": _idea_to_dict(idea)},
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def add_note_to_idea(idea_id: str, text: str) -> str:
        """Add a note to an idea, resetting its decay clock.

        Notes keep ideas alive — each note resets the auto-archive
        timer. Use this to record new thoughts, references, or progress.

        Args:
            idea_id: Idea ID or 4-character prefix.
            text: Note text to add.
        """

        idea = fast_path.add_idea_note(data_dir, idea_id, text)
        if idea is None:
            return json.dumps({"error": f"Idea '{idea_id}' not found"})

        _rebuild_index(data_dir)
        return json.dumps(
            {"success": True, "idea": _idea_to_dict(idea)},
            indent=2,
        )

    @mcp.tool()
    def develop_idea(idea_id: str, note: str) -> str:
        """Advance an idea from 'spark' to 'developing' status.

        Requires the idea to be in 'spark' status. Adds a note
        and extends the decay window from 30 to 90 days.

        Args:
            idea_id: Idea ID or 4-character prefix.
            note: Development note explaining why this idea has legs.
        """

        idea = fast_path.develop_idea(data_dir, idea_id, note)
        if idea is None:
            return json.dumps(
                {"error": f"Idea '{idea_id}' not found or not in 'spark' status"}
            )

        _rebuild_index(data_dir)
        return json.dumps(
            {"success": True, "idea": _idea_to_dict(idea)},
            indent=2,
        )

    @mcp.tool()
    def mature_idea(idea_id: str, note: str) -> str:
        """Advance an idea from 'developing' to 'mature' status.

        Requires the idea to be in 'developing' status. Mature ideas
        do not decay — they persist until promoted to a task or archived.

        Args:
            idea_id: Idea ID or 4-character prefix.
            note: Maturity note explaining why this idea is ready.
        """

        idea = fast_path.mature_idea(data_dir, idea_id, note)
        if idea is None:
            return json.dumps(
                {"error": f"Idea '{idea_id}' not found or not in 'developing' status"}
            )

        _rebuild_index(data_dir)
        return json.dumps(
            {"success": True, "idea": _idea_to_dict(idea)},
            indent=2,
        )

    @mcp.tool()
    def promote_idea(
        idea_id: str,
        deadline: str | None = None,
        parent_id: str | None = None,
    ) -> str:
        """Graduate an idea to a task.

        Creates a new task from the idea's thought text, copies tags,
        and archives the idea with reason 'promoted'. The idea records
        which task it was promoted to.

        Args:
            idea_id: Idea ID or 4-character prefix.
            deadline: Optional deadline for the new task (YYYY-MM-DD).
            parent_id: Optional parent task ID to create as subtask.
        """
        from datetime import date as _date


        parsed_deadline = None
        if deadline:
            try:
                parsed_deadline = _date.fromisoformat(deadline)
            except ValueError:
                return json.dumps(
                    {"error": f"Invalid deadline format: '{deadline}'. Use YYYY-MM-DD."}
                )

        result = fast_path.promote_idea(
            data_dir,
            idea_id,
            deadline=parsed_deadline,
            parent_id=parent_id,
        )
        if result is None:
            return json.dumps(
                {"error": f"Idea '{idea_id}' not found or already archived/promoted"}
            )

        idea, task = result
        _rebuild_index(data_dir)
        return json.dumps(
            {
                "success": True,
                "idea": _idea_to_dict(idea),
                "task": _task_to_dict(task),
            },
            indent=2,
        )

    @mcp.tool()
    def archive_idea(idea_id: str) -> str:
        """Intentionally archive an idea.

        Marks the idea as archived with reason 'manual'. Archived ideas
        are preserved in history but excluded from active lists.

        Args:
            idea_id: Idea ID or 4-character prefix.
        """

        idea = fast_path.archive_idea(data_dir, idea_id)
        if idea is None:
            return json.dumps({"error": f"Idea '{idea_id}' not found"})

        _rebuild_index(data_dir)
        return json.dumps(
            {"success": True, "idea": _idea_to_dict(idea)},
            indent=2,
        )

    # ------------------------------------------------------------------
    # Resources
    # ------------------------------------------------------------------

    @mcp.resource("marvin://tasks")
    def get_tasks() -> str:
        """Current task data (tasks.json)."""
        tasks_path = data_dir / "tasks.json"
        if tasks_path.exists():
            return tasks_path.read_text()
        return '{"project": "default", "tasks": []}'

    @mcp.resource("marvin://collaborators")
    def get_collaborators() -> str:
        """Current collaborator data (collaborators.json)."""
        collab_path = data_dir / "collaborators.json"
        if collab_path.exists():
            return collab_path.read_text()
        return '{"collaborators": []}'

    @mcp.resource("marvin://ideas")
    def get_ideas() -> str:
        """Current idea data (ideas.json)."""
        ideas_path = data_dir / "ideas.json"
        if ideas_path.exists():
            return ideas_path.read_text()
        return '{"ideas": []}'

    @mcp.resource("marvin://instructions")
    def get_instructions() -> str:
        """Agent guidance (GEMINI.md) for task management conventions."""
        gemini_path = data_dir / "GEMINI.md"
        if gemini_path.exists():
            return gemini_path.read_text()
        return "# No GEMINI.md found"

    mcp.run()


if __name__ == "__main__":
    main()
