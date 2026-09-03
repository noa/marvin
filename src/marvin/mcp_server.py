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



def create_mcp_server(data_dir: Path | str | None = None):
    """Create and configure the FastMCP server instance."""
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

    if data_dir is None:
        data_dir = Path(_get_data_dir()).expanduser()
    elif isinstance(data_dir, str):
        data_dir = Path(data_dir).expanduser()

    mcp = FastMCP(
        "marvin",
        instructions=(
            "Task management for academic PIs. "
            "Manages tasks, deadlines, collaborators, and waiting-on items."
        ),
    )

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
    # Proactive / Daemon Tools (Always-On Marvin)
    # ------------------------------------------------------------------

    @mcp.tool()
    def get_proactive_pings(
        dry_run: bool = True,
        bypass_filters: bool = False,
    ) -> str:
        """Evaluate current knowledge state and return proactive alerts.

        Assesses upcoming deadlines, collaborator blockers, subtask bottlenecks,
        and idea decay.

        Args:
            dry_run: If True, do not record notifications or mutate cooldowns.
            bypass_filters: If True, bypass quiet hours and daily rate limits.
        """
        from marvin.daemon import MarvinDaemon
        daemon = MarvinDaemon(data_dir)
        actionable, squelched = daemon.run_once(
            notify=False,
            dry_run=dry_run,
            bypass_filters=bypass_filters,
        )

        return json.dumps(
            {
                "total_actionable": len(actionable),
                "actionable_alerts": [a.model_dump(mode="json") for a in actionable],
                "total_squelched": len(squelched),
                "squelched_alerts": [
                    {"alert": a.model_dump(mode="json"), "reason": reason}
                    for a, reason in squelched
                ],
            },
            indent=2,
        )

    @mcp.tool()
    def snooze_alert(
        item_id: str,
        days: int = 1,
        hours: int = 0,
        reason: str = "",
    ) -> str:
        """Snooze proactive alerts for a specific task or idea.

        Args:
            item_id: Task ID, idea ID, or 4-character prefix.
            days: Number of days to snooze.
            hours: Number of hours to snooze.
            reason: Optional explanation for snooze.
        """
        from datetime import datetime as _dt, timedelta as _td
        from marvin.daemon_schema import load_daemon_state, save_daemon_state

        now = _dt.now()
        target_dt = now + _td(days=days, hours=hours)

        clean_arg = item_id.lower().strip()
        canonical_id = item_id
        tf = fast_path.load_tasks(data_dir)
        for t in tf.tasks:
            if t.id.lower() == clean_arg or (len(clean_arg) >= 4 and t.id.lower().startswith(clean_arg)):
                canonical_id = t.id
                break
        else:
            ideas = fast_path.load_ideas(data_dir)
            for i in ideas.ideas:
                if i.id.lower() == clean_arg or (len(clean_arg) >= 4 and i.id.lower().startswith(clean_arg)):
                    canonical_id = i.id
                    break

        state = load_daemon_state(data_dir)
        state.snooze(canonical_id, target_dt, reason=reason, now_dt=now)
        save_daemon_state(state, data_dir)

        return json.dumps(
            {
                "success": True,
                "item_id": canonical_id,
                "snoozed_until": target_dt.isoformat(),
                "reason": reason,
            },
            indent=2,
        )

    @mcp.tool()
    def unsnooze_alert(item_id: str) -> str:
        """Remove an active snooze for a task or idea.

        Args:
            item_id: Task ID, idea ID, or 4-character prefix.
        """
        from marvin.daemon_schema import load_daemon_state, save_daemon_state

        state = load_daemon_state(data_dir)
        removed = state.unsnooze(item_id)
        if removed:
            save_daemon_state(state, data_dir)

        return json.dumps(
            {
                "success": removed,
                "item_id": item_id,
                "message": f"Removed snooze for '{item_id}'" if removed else f"No active snooze found for '{item_id}'",
            },
            indent=2,
        )

    @mcp.tool()
    def get_daemon_status() -> str:
        """Get the current state and configuration of the Always-On daemon."""
        from marvin.daemon_schema import load_daemon_state

        state = load_daemon_state(data_dir)
        return json.dumps(state.model_dump(mode="json"), indent=2)

    # ------------------------------------------------------------------
    # Email Tools (Microsoft Graph Outlook Integration)
    # ------------------------------------------------------------------

    @mcp.tool()
    def get_email_status() -> str:
        """Check Microsoft Graph Outlook connection and account status."""
        from marvin.email_client import MicrosoftGraphClient, load_email_auth

        client = MicrosoftGraphClient(data_dir)
        auth = load_email_auth(data_dir)
        if not auth:
            return json.dumps(
                {
                    "authenticated": False,
                    "message": "Not signed in. Run 'marvin email login' in terminal to authenticate.",
                },
                indent=2,
            )

        return json.dumps(
            {
                "authenticated": True,
                "account_email": auth.account_email,
                "account_name": auth.account_name,
                "client_id": auth.client_id,
                "tenant_id": auth.tenant_id,
                "scopes": auth.scopes,
                "is_expired": auth.is_expired(buffer_seconds=0),
            },
            indent=2,
        )

    @mcp.tool()
    def list_emails(
        limit: int = 10,
        unread_only: bool = False,
        folder: str = "inbox",
        query: str | None = None,
    ) -> str:
        """List recent emails from Microsoft Graph Outlook with collaborator matching.

        Args:
            limit: Maximum number of emails to retrieve (default 10).
            unread_only: If True, only retrieve unread emails.
            folder: Mail folder name ('inbox' or 'all').
            query: Search query to filter messages by keyword.
        """
        from marvin.email_client import MicrosoftGraphClient, NotAuthenticatedError, EmailClientError
        from marvin.email_triage import get_triage_candidates

        client = MicrosoftGraphClient(data_dir)
        try:
            candidates = get_triage_candidates(
                data_dir,
                client,
                limit=limit,
                unread_only=unread_only,
                include_triaged=True,
            )
            return json.dumps(
                {
                    "total": len(candidates),
                    "emails": [c.to_dict() for c in candidates],
                },
                indent=2,
            )
        except NotAuthenticatedError:
            return json.dumps(
                {"error": "Not authenticated with Microsoft Graph. Run 'marvin email login' in CLI first."},
                indent=2,
            )
        except EmailClientError as e:
            return json.dumps({"error": str(e)}, indent=2)

    @mcp.tool()
    def get_email(email_id: str) -> str:
        """Get full details and clean body content of an email message.

        Args:
            email_id: The ID or short prefix of the email message.
        """
        from marvin.email_client import MicrosoftGraphClient, NotAuthenticatedError, EmailClientError

        client = MicrosoftGraphClient(data_dir)
        try:
            try:
                msg = client.get_message(email_id)
            except Exception:
                full_id = email_id
                try:
                    for m in client.list_messages(limit=50):
                        if m.id.startswith(email_id) or m.short_id.startswith(email_id):
                            full_id = m.id
                            break
                except Exception:
                    pass
                msg = client.get_message(full_id)
            return json.dumps(
                {
                    "id": msg.id,
                    "short_id": msg.short_id,
                    "subject": msg.subject,
                    "from": msg.sender.display() if msg.sender else None,
                    "from_address": msg.sender.address if msg.sender else None,
                    "to": [r.display() for r in msg.to_recipients],
                    "cc": [r.display() for r in msg.cc_recipients],
                    "received_at": msg.received_datetime.isoformat() if msg.received_datetime else None,
                    "is_read": msg.is_read,
                    "importance": msg.importance,
                    "has_attachments": msg.has_attachments,
                    "web_link": msg.web_link,
                    "body": msg.clean_text_body(),
                },
                indent=2,
            )
        except NotAuthenticatedError:
            return json.dumps(
                {"error": "Not authenticated with Microsoft Graph. Run 'marvin email login' in CLI first."},
                indent=2,
            )
        except EmailClientError as e:
            return json.dumps({"error": str(e)}, indent=2)

    @mcp.tool()
    def triage_emails(limit: int = 10, unread_only: bool = True) -> str:
        """Analyze unread emails against open tasks and waiting-on blockers.

        Evaluates incoming messages to identify:
        - Blocker resolutions (emails from people you are waiting on)
        - Actionable emails with deadlines or requests
        - Collaborator communications

        Args:
            limit: Maximum number of unread emails to inspect (default 10).
            unread_only: If True, only evaluate unread emails.
        """
        from marvin.email_client import MicrosoftGraphClient, NotAuthenticatedError, EmailClientError
        from marvin.email_triage import get_triage_candidates

        client = MicrosoftGraphClient(data_dir)
        try:
            candidates = get_triage_candidates(
                data_dir,
                client,
                limit=limit,
                unread_only=unread_only,
                include_triaged=False,
            )

            blocker_resolutions = [c.to_dict() for c in candidates if c.waiting_tasks]
            actionable_emails = [
                c.to_dict()
                for c in candidates
                if c.suggested_action == "create_task" and not c.waiting_tasks
            ]
            other_emails = [
                c.to_dict()
                for c in candidates
                if not c.waiting_tasks and c.suggested_action != "create_task"
            ]

            return json.dumps(
                {
                    "total_unread_candidates": len(candidates),
                    "blocker_resolutions": blocker_resolutions,
                    "suggested_tasks": actionable_emails,
                    "other_inbox_items": other_emails,
                },
                indent=2,
            )
        except NotAuthenticatedError:
            return json.dumps(
                {"error": "Not authenticated with Microsoft Graph. Run 'marvin email login' in CLI first."},
                indent=2,
            )
        except EmailClientError as e:
            return json.dumps({"error": str(e)}, indent=2)

    @mcp.tool()
    def create_task_from_email(
        email_id: str,
        description: str | None = None,
        deadline: str | None = None,
        priority: str | None = None,
        waiting_on: str | None = None,
    ) -> str:
        """Create a task linked to an email message and mark the email triaged.

        Args:
            email_id: ID of the email message.
            description: Task description (defaults to email subject).
            deadline: Optional deadline date (YYYY-MM-DD).
            priority: Priority level ('high', 'medium', 'low').
            waiting_on: Optional name of person waiting on.
        """
        from marvin.email_client import MicrosoftGraphClient
        from marvin.email_triage import create_task_from_email as _create_task_from_email

        client = MicrosoftGraphClient(data_dir)
        try:
            msg = client.get_message(email_id)
            full_id = msg.id
        except Exception:
            full_id = email_id
            try:
                for m in client.list_messages(limit=50):
                    if m.id.startswith(email_id) or m.short_id.startswith(email_id):
                        full_id = m.id
                        break
            except Exception:
                pass
            msg = client.get_message(full_id)

        task = _create_task_from_email(
            data_dir,
            msg,
            description=description,
            deadline=deadline,
            priority=priority,
            waiting_on=waiting_on,
        )
        _rebuild_index(data_dir)
        client.mark_as_read(full_id)

        return json.dumps(
            {
                "success": True,
                "task": _task_to_dict(task),
                "message": f"Created task [{task.id[:4]}] {task.description} linked to email",
            },
            indent=2,
        )

    @mcp.tool()
    def resolve_email_blocker(
        task_id: str,
        email_id: str | None = None,
        note: str | None = None,
    ) -> str:
        """Resolve a waiting-on blocker on a task using an email.

        Args:
            task_id: ID of the task to unblock.
            email_id: Optional ID of the email that resolved the blocker.
            note: Optional custom resolution note.
        """
        from marvin.email_client import MicrosoftGraphClient
        from marvin.email_triage import resolve_email_blocker as _resolve_email_blocker

        client = MicrosoftGraphClient(data_dir)
        msg = None
        if email_id:
            try:
                msg = client.get_message(email_id)
                client.mark_as_read(msg.id)
            except Exception:
                full_id = email_id
                try:
                    for m in client.list_messages(limit=50):
                        if m.id.startswith(email_id) or m.short_id.startswith(email_id):
                            full_id = m.id
                            break
                    msg = client.get_message(full_id)
                    client.mark_as_read(full_id)
                except Exception:
                    pass

        task = _resolve_email_blocker(data_dir, task_id, email=msg, note=note)
        return json.dumps(
            {
                "success": True,
                "task": _task_to_dict(task),
                "message": f"Unblocked task [{task.id[:4]}] {task.description}",
            },
            indent=2,
        )

    @mcp.tool()
    def mark_email_read(email_id: str) -> str:
        """Mark an email as read on Microsoft Graph and mark as triaged.

        Args:
            email_id: ID of the email to mark as read.
        """
        from marvin.email_client import MicrosoftGraphClient
        from marvin.email_triage import dismiss_email

        client = MicrosoftGraphClient(data_dir)
        full_id = email_id
        try:
            client.mark_as_read(email_id)
        except Exception:
            pass
        dismiss_email(data_dir, full_id)
        return json.dumps({"success": True, "email_id": full_id}, indent=2)

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

    return mcp


def main():
    """Entry point for the marvin-mcp command."""
    # Allow --data-dir override via argv
    data_dir_str = _get_data_dir()
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--data-dir" and i < len(sys.argv) - 1:
            data_dir_str = sys.argv[i + 1]
            break

    data_dir = Path(data_dir_str).expanduser()
    mcp = create_mcp_server(data_dir)
    mcp.run()


if __name__ == "__main__":
    main()
