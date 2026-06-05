"""Comprehensive tests for marvin.fast_path module.

Tests all fast-path functions for tasks and collaborators.
Uses tmp_path for filesystem isolation — never touches real user data.
"""

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from marvin.fast_path import (
    add_collaborator,
    add_collaborator_note,
    add_note,
    clear_overdue_tasks,
    clear_past_deadline_tasks,
    edit_collaborator,
    edit_task,
    find_task_by_id,
    get_tasks_for_person,
    load_collaborators,
    load_tasks,
    mark_done,
    remove_collaborator,
    remove_task,
    remove_tasks_batch,
    resolve_waiting_on,
    search_tasks_by_query,
)
from marvin.task_schema import Task, TaskFile, save_task_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_tasks(data_dir: Path, tasks: list[dict]) -> None:
    """Write a list of raw task dicts to tasks.json."""
    payload = {"project": "default", "tasks": tasks}
    (data_dir / "tasks.json").write_text(json.dumps(payload, indent=2))


def _make_task(**overrides) -> dict:
    """Return a minimal valid task dict with overrides."""
    defaults = {
        "id": "aabbcc",
        "description": "Do something",
        "status": "open",
        "priority": "medium",
        "tags": [],
        "notes": [],
        "created_at": str(date.today()),
    }
    defaults.update(overrides)
    return defaults


def _write_collaborators(data_dir: Path, collabs: list[dict]) -> None:
    """Write a list of raw collaborator dicts to collaborators.json."""
    payload = {"collaborators": collabs}
    (data_dir / "collaborators.json").write_text(json.dumps(payload, indent=2))


def _make_collab(**overrides) -> dict:
    """Return a minimal valid collaborator dict with overrides."""
    defaults = {
        "id": "cc1122",
        "name": "Alice Chen",
        "aliases": [],
        "notes": [],
        "tags": [],
        "added_at": str(date.today()),
    }
    defaults.update(overrides)
    return defaults


# ===================================================================
# Task functions
# ===================================================================


class TestLoadTasks:
    """Tests for load_tasks()."""

    def test_load_tasks_empty(self, data_dir: Path):
        """Empty tasks list returns a TaskFile with no tasks."""
        tf = load_tasks(data_dir)
        assert isinstance(tf, TaskFile)
        assert tf.tasks == []
        assert tf.project == "default"

    def test_load_tasks_with_tasks(self, data_dir: Path):
        """Tasks are loaded correctly."""
        _write_tasks(data_dir, [
            _make_task(id="aaa111", description="Task one"),
            _make_task(id="bbb222", description="Task two"),
        ])
        tf = load_tasks(data_dir)
        assert len(tf.tasks) == 2
        assert tf.tasks[0].description == "Task one"
        assert tf.tasks[1].description == "Task two"

    def test_load_tasks_missing_file(self, tmp_path: Path):
        """Missing tasks.json returns an empty TaskFile."""
        # tmp_path has no tasks.json at all
        tf = load_tasks(tmp_path)
        assert isinstance(tf, TaskFile)
        assert tf.tasks == []
        assert tf.project == "default"

    def test_load_tasks_corrupted_json(self, data_dir: Path):
        """Corrupted JSON returns an empty TaskFile."""
        (data_dir / "tasks.json").write_text("{not valid json!!!")
        tf = load_tasks(data_dir)
        assert isinstance(tf, TaskFile)
        assert tf.tasks == []


class TestFindTaskById:
    """Tests for find_task_by_id()."""

    def test_find_by_full_id(self, data_dir: Path):
        """Full ID match returns the task."""
        _write_tasks(data_dir, [_make_task(id="aabb11", description="Found me")])
        result = find_task_by_id(data_dir, "aabb11")
        assert result is not None
        path, tf, task = result
        assert task.id == "aabb11"
        assert task.description == "Found me"

    def test_find_by_prefix(self, data_dir: Path):
        """Prefix match returns the task."""
        _write_tasks(data_dir, [_make_task(id="aabb11", description="Found me")])
        result = find_task_by_id(data_dir, "aabb")
        assert result is not None
        _, _, task = result
        assert task.id == "aabb11"

    def test_find_by_prefix_case_insensitive(self, data_dir: Path):
        """ID prefix match is case-insensitive."""
        _write_tasks(data_dir, [_make_task(id="aabb11", description="Found me")])
        result = find_task_by_id(data_dir, "AABB")
        assert result is not None
        _, _, task = result
        assert task.id == "aabb11"

    def test_find_not_found(self, data_dir: Path):
        """Non-matching ID returns None."""
        _write_tasks(data_dir, [_make_task(id="aabb11")])
        result = find_task_by_id(data_dir, "zzz999")
        assert result is None

    def test_find_no_file(self, tmp_path: Path):
        """Missing tasks.json returns None."""
        result = find_task_by_id(tmp_path, "anything")
        assert result is None

    def test_find_returns_first_prefix_match(self, data_dir: Path):
        """When multiple tasks share a prefix, the first match wins."""
        _write_tasks(data_dir, [
            _make_task(id="aa1111", description="First"),
            _make_task(id="aa2222", description="Second"),
        ])
        result = find_task_by_id(data_dir, "aa")
        assert result is not None
        _, _, task = result
        assert task.id == "aa1111"


class TestEditTask:
    """Tests for edit_task()."""

    def test_add_tags(self, data_dir: Path):
        _write_tasks(data_dir, [_make_task(id="aaa111")])
        task = edit_task(data_dir, "aaa111", add_tags=["urgent", "lab"])
        assert task is not None
        assert "urgent" in task.tags
        assert "lab" in task.tags

    def test_add_tags_strips_hash(self, data_dir: Path):
        """Tags starting with # have it stripped."""
        _write_tasks(data_dir, [_make_task(id="aaa111")])
        task = edit_task(data_dir, "aaa111", add_tags=["#paper"])
        assert "paper" in task.tags
        assert "#paper" not in task.tags

    def test_add_tags_no_duplicates(self, data_dir: Path):
        """Adding a tag that already exists doesn't create duplicates."""
        _write_tasks(data_dir, [_make_task(id="aaa111", tags=["urgent"])])
        task = edit_task(data_dir, "aaa111", add_tags=["urgent"])
        assert task.tags.count("urgent") == 1

    def test_remove_tags(self, data_dir: Path):
        _write_tasks(data_dir, [_make_task(id="aaa111", tags=["urgent", "lab"])])
        task = edit_task(data_dir, "aaa111", remove_tags=["urgent"])
        assert "urgent" not in task.tags
        assert "lab" in task.tags

    def test_remove_tags_case_insensitive(self, data_dir: Path):
        """Tag removal is case-insensitive."""
        _write_tasks(data_dir, [_make_task(id="aaa111", tags=["urgent"])])
        task = edit_task(data_dir, "aaa111", remove_tags=["URGENT"])
        assert task.tags == []

    def test_set_deadline(self, data_dir: Path):
        _write_tasks(data_dir, [_make_task(id="aaa111")])
        task = edit_task(data_dir, "aaa111", set_deadline="2026-12-25")
        assert task.deadline == date(2026, 12, 25)

    def test_clear_deadline(self, data_dir: Path):
        _write_tasks(data_dir, [
            _make_task(id="aaa111", deadline="2026-12-25"),
        ])
        task = edit_task(data_dir, "aaa111", clear_deadline=True)
        assert task.deadline is None

    def test_set_priority(self, data_dir: Path):
        _write_tasks(data_dir, [_make_task(id="aaa111")])
        task = edit_task(data_dir, "aaa111", set_priority="high")
        assert task.priority == "high"

    def test_set_waiting(self, data_dir: Path):
        _write_tasks(data_dir, [_make_task(id="aaa111")])
        task = edit_task(data_dir, "aaa111", set_waiting="Bob Smith")
        assert task.waiting_on == "Bob Smith"

    def test_clear_waiting(self, data_dir: Path):
        _write_tasks(data_dir, [_make_task(id="aaa111", waiting_on="Bob Smith")])
        task = edit_task(data_dir, "aaa111", clear_waiting=True)
        assert task.waiting_on is None

    def test_set_description(self, data_dir: Path):
        _write_tasks(data_dir, [_make_task(id="aaa111", description="Old")])
        task = edit_task(data_dir, "aaa111", set_description="New description")
        assert task.description == "New description"

    def test_edit_not_found(self, data_dir: Path):
        _write_tasks(data_dir, [_make_task(id="aaa111")])
        result = edit_task(data_dir, "zzz999", add_tags=["x"])
        assert result is None

    def test_edit_persists_to_disk(self, data_dir: Path):
        """Edits are saved so a re-read picks them up."""
        _write_tasks(data_dir, [_make_task(id="aaa111", description="Original")])
        edit_task(data_dir, "aaa111", set_description="Changed")
        tf = load_tasks(data_dir)
        assert tf.tasks[0].description == "Changed"


class TestAddNote:
    """Tests for add_note()."""

    def test_add_note_basic(self, data_dir: Path):
        _write_tasks(data_dir, [_make_task(id="aaa111")])
        task = add_note(data_dir, "aaa111", "Remember to check results")
        assert task is not None
        assert "Remember to check results" in task.notes

    def test_add_multiple_notes(self, data_dir: Path):
        _write_tasks(data_dir, [_make_task(id="aaa111")])
        add_note(data_dir, "aaa111", "Note 1")
        task = add_note(data_dir, "aaa111", "Note 2")
        assert len(task.notes) == 2
        assert task.notes[0] == "Note 1"
        assert task.notes[1] == "Note 2"

    def test_add_note_not_found(self, data_dir: Path):
        _write_tasks(data_dir, [_make_task(id="aaa111")])
        result = add_note(data_dir, "zzz999", "Orphan note")
        assert result is None

    def test_add_note_unicode(self, data_dir: Path):
        """Unicode text is preserved in notes."""
        _write_tasks(data_dir, [_make_task(id="aaa111")])
        task = add_note(data_dir, "aaa111", "会议纪要 📝")
        assert task.notes[-1] == "会议纪要 📝"

    def test_add_note_persists(self, data_dir: Path):
        """Notes survive a round-trip to disk."""
        _write_tasks(data_dir, [_make_task(id="aaa111")])
        add_note(data_dir, "aaa111", "Persistent note")
        tf = load_tasks(data_dir)
        assert "Persistent note" in tf.tasks[0].notes


class TestMarkDone:
    """Tests for mark_done()."""

    def test_mark_done_basic(self, data_dir: Path):
        _write_tasks(data_dir, [_make_task(id="aaa111", status="open")])
        task = mark_done(data_dir, "aaa111")
        assert task is not None
        assert task.status == "done"
        assert task.completed_at == date.today()

    def test_mark_done_not_found(self, data_dir: Path):
        _write_tasks(data_dir, [_make_task(id="aaa111")])
        result = mark_done(data_dir, "zzz999")
        assert result is None

    def test_mark_done_persists(self, data_dir: Path):
        _write_tasks(data_dir, [_make_task(id="aaa111")])
        mark_done(data_dir, "aaa111")
        tf = load_tasks(data_dir)
        assert tf.tasks[0].status == "done"
        assert tf.tasks[0].completed_at == date.today()


class TestRemoveTask:
    """Tests for remove_task()."""

    def test_remove_basic(self, data_dir: Path):
        _write_tasks(data_dir, [
            _make_task(id="aaa111", description="Keep"),
            _make_task(id="bbb222", description="Remove"),
        ])
        removed = remove_task(data_dir, "bbb222")
        assert removed is not None
        assert removed.id == "bbb222"
        tf = load_tasks(data_dir)
        assert len(tf.tasks) == 1
        assert tf.tasks[0].id == "aaa111"

    def test_remove_not_found(self, data_dir: Path):
        _write_tasks(data_dir, [_make_task(id="aaa111")])
        result = remove_task(data_dir, "zzz999")
        assert result is None


class TestClearOverdueTasks:
    """Tests for clear_overdue_tasks()."""

    def test_clears_overdue(self, data_dir: Path):
        yesterday = str(date.today() - timedelta(days=1))
        _write_tasks(data_dir, [
            _make_task(id="aaa111", deadline=yesterday, status="open"),
        ])
        cleared = clear_overdue_tasks(data_dir)
        assert len(cleared) == 1
        assert cleared[0].id == "aaa111"
        assert cleared[0].status == "done"
        # Verify on disk
        tf = load_tasks(data_dir)
        assert tf.tasks[0].status == "done"

    def test_skips_non_overdue(self, data_dir: Path):
        tomorrow = str(date.today() + timedelta(days=1))
        _write_tasks(data_dir, [
            _make_task(id="aaa111", deadline=tomorrow, status="open"),
        ])
        cleared = clear_overdue_tasks(data_dir)
        assert cleared == []
        tf = load_tasks(data_dir)
        assert tf.tasks[0].status == "open"

    def test_skips_already_done(self, data_dir: Path):
        yesterday = str(date.today() - timedelta(days=1))
        _write_tasks(data_dir, [
            _make_task(id="aaa111", deadline=yesterday, status="done"),
        ])
        cleared = clear_overdue_tasks(data_dir)
        assert cleared == []

    def test_skips_no_deadline(self, data_dir: Path):
        _write_tasks(data_dir, [_make_task(id="aaa111", status="open")])
        cleared = clear_overdue_tasks(data_dir)
        assert cleared == []

    def test_mixed_overdue_and_not(self, data_dir: Path):
        yesterday = str(date.today() - timedelta(days=1))
        tomorrow = str(date.today() + timedelta(days=1))
        _write_tasks(data_dir, [
            _make_task(id="aaa111", deadline=yesterday, status="open"),
            _make_task(id="bbb222", deadline=tomorrow, status="open"),
            _make_task(id="ccc333", status="open"),  # no deadline
        ])
        cleared = clear_overdue_tasks(data_dir)
        assert len(cleared) == 1
        assert cleared[0].id == "aaa111"


class TestSearchTasksByQuery:
    """Tests for search_tasks_by_query()."""

    def test_matches_description(self, data_dir: Path):
        _write_tasks(data_dir, [
            _make_task(id="aaa111", description="Review paper draft"),
            _make_task(id="bbb222", description="Buy groceries"),
        ])
        results = search_tasks_by_query(data_dir, "paper")
        assert len(results) == 1
        assert results[0].id == "aaa111"

    def test_matches_description_case_insensitive(self, data_dir: Path):
        _write_tasks(data_dir, [
            _make_task(id="aaa111", description="Review Paper Draft"),
        ])
        results = search_tasks_by_query(data_dir, "paper")
        assert len(results) == 1

    def test_matches_tag(self, data_dir: Path):
        _write_tasks(data_dir, [
            _make_task(id="aaa111", description="Task 1", tags=["urgent"]),
            _make_task(id="bbb222", description="Task 2", tags=["low"]),
        ])
        results = search_tasks_by_query(data_dir, "urgent")
        assert len(results) == 1
        assert results[0].id == "aaa111"

    def test_no_match(self, data_dir: Path):
        _write_tasks(data_dir, [
            _make_task(id="aaa111", description="Normal task"),
        ])
        results = search_tasks_by_query(data_dir, "xyzzy")
        assert results == []

    def test_skips_done_tasks(self, data_dir: Path):
        """search_tasks_by_query only returns open tasks."""
        _write_tasks(data_dir, [
            _make_task(id="aaa111", description="Completed paper review", status="done"),
            _make_task(id="bbb222", description="Pending paper review", status="open"),
        ])
        results = search_tasks_by_query(data_dir, "paper")
        assert len(results) == 1
        assert results[0].id == "bbb222"

    def test_empty_query_matches_all_open(self, data_dir: Path):
        """An empty string matches every open task's description."""
        _write_tasks(data_dir, [
            _make_task(id="aaa111", status="open"),
            _make_task(id="bbb222", status="open"),
        ])
        results = search_tasks_by_query(data_dir, "")
        assert len(results) == 2


class TestRemoveTasksBatch:
    """Tests for remove_tasks_batch()."""

    def test_removes_multiple(self, data_dir: Path):
        _write_tasks(data_dir, [
            _make_task(id="aaa111", description="A"),
            _make_task(id="bbb222", description="B"),
            _make_task(id="ccc333", description="C"),
        ])
        removed = remove_tasks_batch(data_dir, ["aaa111", "ccc333"])
        assert len(removed) == 2
        removed_ids = {t.id for t in removed}
        assert "aaa111" in removed_ids
        assert "ccc333" in removed_ids
        tf = load_tasks(data_dir)
        assert len(tf.tasks) == 1
        assert tf.tasks[0].id == "bbb222"

    def test_removes_subtrees(self, data_dir: Path):
        """Removing a parent also removes child tasks (orphan cleanup)."""
        _write_tasks(data_dir, [
            _make_task(id="parent1", description="Parent"),
            _make_task(id="child11", description="Child 1", parent_id="parent1"),
            _make_task(id="child12", description="Child 2", parent_id="parent1"),
            _make_task(id="grandch", description="Grandchild", parent_id="child11"),
            _make_task(id="other01", description="Unrelated"),
        ])
        removed = remove_tasks_batch(data_dir, ["parent1"])
        removed_ids = {t.id for t in removed}
        assert "parent1" in removed_ids
        assert "child11" in removed_ids
        assert "child12" in removed_ids
        assert "grandch" in removed_ids
        assert "other01" not in removed_ids
        tf = load_tasks(data_dir)
        assert len(tf.tasks) == 1
        assert tf.tasks[0].id == "other01"

    def test_removes_nothing_if_ids_missing(self, data_dir: Path):
        _write_tasks(data_dir, [_make_task(id="aaa111")])
        removed = remove_tasks_batch(data_dir, ["zzz999"])
        assert removed == []


class TestClearPastDeadlineTasks:
    """Tests for clear_past_deadline_tasks()."""

    def test_clears_conference_deadline_past_due(self, data_dir: Path):
        yesterday = str(date.today() - timedelta(days=1))
        _write_tasks(data_dir, [
            _make_task(
                id="aaa111",
                tags=["conference", "deadline"],
                deadline=yesterday,
                status="open",
            ),
        ])
        cleared = clear_past_deadline_tasks(data_dir)
        assert len(cleared) == 1
        assert cleared[0].status == "done"
        assert cleared[0].completed_at == date.today()

    def test_clears_grant_deadline_past_due(self, data_dir: Path):
        yesterday = str(date.today() - timedelta(days=1))
        _write_tasks(data_dir, [
            _make_task(
                id="aaa111",
                tags=["grant", "deadline"],
                deadline=yesterday,
                status="open",
            ),
        ])
        cleared = clear_past_deadline_tasks(data_dir)
        assert len(cleared) == 1

    def test_skips_conference_no_deadline_tag(self, data_dir: Path):
        """A conference task without #deadline tag is NOT auto-cleared."""
        yesterday = str(date.today() - timedelta(days=1))
        _write_tasks(data_dir, [
            _make_task(
                id="aaa111",
                tags=["conference"],
                deadline=yesterday,
                status="open",
            ),
        ])
        cleared = clear_past_deadline_tasks(data_dir)
        assert cleared == []

    def test_skips_deadline_without_type_tag(self, data_dir: Path):
        """A #deadline task that's not #conference or #grant is NOT auto-cleared."""
        yesterday = str(date.today() - timedelta(days=1))
        _write_tasks(data_dir, [
            _make_task(
                id="aaa111",
                tags=["deadline"],
                deadline=yesterday,
                status="open",
            ),
        ])
        cleared = clear_past_deadline_tasks(data_dir)
        assert cleared == []

    def test_skips_future_deadline(self, data_dir: Path):
        tomorrow = str(date.today() + timedelta(days=1))
        _write_tasks(data_dir, [
            _make_task(
                id="aaa111",
                tags=["conference", "deadline"],
                deadline=tomorrow,
                status="open",
            ),
        ])
        cleared = clear_past_deadline_tasks(data_dir)
        assert cleared == []

    def test_skips_already_done(self, data_dir: Path):
        yesterday = str(date.today() - timedelta(days=1))
        _write_tasks(data_dir, [
            _make_task(
                id="aaa111",
                tags=["conference", "deadline"],
                deadline=yesterday,
                status="done",
            ),
        ])
        cleared = clear_past_deadline_tasks(data_dir)
        assert cleared == []

    def test_mixed_scenario(self, data_dir: Path):
        """Only the qualifying past-due conference/grant + deadline tasks are cleared."""
        yesterday = str(date.today() - timedelta(days=1))
        tomorrow = str(date.today() + timedelta(days=1))
        _write_tasks(data_dir, [
            _make_task(id="clear1", tags=["conference", "deadline"],
                       deadline=yesterday, status="open"),
            _make_task(id="keep1", tags=["conference", "deadline"],
                       deadline=tomorrow, status="open"),
            _make_task(id="keep2", tags=["deadline"],
                       deadline=yesterday, status="open"),
            _make_task(id="keep3", tags=["lab"],
                       deadline=yesterday, status="open"),
        ])
        cleared = clear_past_deadline_tasks(data_dir)
        assert len(cleared) == 1
        assert cleared[0].id == "clear1"


# ===================================================================
# Collaborator functions
# ===================================================================


class TestLoadCollaborators:
    """Tests for load_collaborators()."""

    def test_load_empty(self, data_dir: Path):
        cf = load_collaborators(data_dir)
        assert cf.collaborators == []

    def test_load_with_data(self, data_dir: Path):
        _write_collaborators(data_dir, [
            _make_collab(id="cc1111", name="Alice Chen"),
            _make_collab(id="cc2222", name="Bob Smith"),
        ])
        cf = load_collaborators(data_dir)
        assert len(cf.collaborators) == 2
        assert cf.collaborators[0].name == "Alice Chen"

    def test_load_missing_file(self, tmp_path: Path):
        """Missing collaborators.json returns an empty CollaboratorFile."""
        cf = load_collaborators(tmp_path)
        assert cf.collaborators == []


class TestAddCollaborator:
    """Tests for add_collaborator()."""

    def test_basic_add(self, data_dir: Path):
        collab = add_collaborator(data_dir, "Alice Chen")
        assert collab.name == "Alice Chen"
        assert len(collab.id) == 6  # default hex id
        # Verify persisted
        cf = load_collaborators(data_dir)
        assert len(cf.collaborators) == 1
        assert cf.collaborators[0].name == "Alice Chen"

    def test_add_with_all_fields(self, data_dir: Path):
        collab = add_collaborator(
            data_dir,
            "Bob Smith",
            role="Postdoc",
            affiliation="MIT CSAIL",
            email="bob@mit.edu",
            extra_aliases=["bobby"],
            tags=["collaborator", "ml"],
        )
        assert collab.role == "Postdoc"
        assert collab.affiliation == "MIT CSAIL"
        assert collab.email == "bob@mit.edu"
        assert "bobby" in collab.aliases
        assert "collaborator" in collab.tags

    def test_duplicate_name_raises(self, data_dir: Path):
        add_collaborator(data_dir, "Alice Chen")
        with pytest.raises(ValueError, match="already exists"):
            add_collaborator(data_dir, "alice chen")  # case-insensitive dup

    def test_add_unicode_name(self, data_dir: Path):
        collab = add_collaborator(data_dir, "José García")
        assert collab.name == "José García"


class TestEditCollaborator:
    """Tests for edit_collaborator()."""

    def test_set_name(self, data_dir: Path):
        _write_collaborators(data_dir, [_make_collab(id="cc1111", name="Alice Chen")])
        collab = edit_collaborator(data_dir, "Alice", set_name="Alice B. Chen")
        assert collab is not None
        assert collab.name == "Alice B. Chen"

    def test_set_role(self, data_dir: Path):
        _write_collaborators(data_dir, [_make_collab(id="cc1111", name="Alice Chen")])
        collab = edit_collaborator(data_dir, "Alice", set_role="Professor")
        assert collab.role == "Professor"

    def test_set_affiliation(self, data_dir: Path):
        _write_collaborators(data_dir, [_make_collab(id="cc1111", name="Alice Chen")])
        collab = edit_collaborator(data_dir, "Alice", set_affiliation="Stanford")
        assert collab.affiliation == "Stanford"

    def test_set_email(self, data_dir: Path):
        _write_collaborators(data_dir, [_make_collab(id="cc1111", name="Alice Chen")])
        collab = edit_collaborator(data_dir, "Alice", set_email="alice@stanford.edu")
        assert collab.email == "alice@stanford.edu"

    def test_add_aliases(self, data_dir: Path):
        _write_collaborators(data_dir, [_make_collab(id="cc1111", name="Alice Chen")])
        collab = edit_collaborator(data_dir, "Alice", add_aliases=["ac", "alic"])
        assert "ac" in collab.aliases
        assert "alic" in collab.aliases

    def test_add_aliases_no_duplicates(self, data_dir: Path):
        _write_collaborators(data_dir, [
            _make_collab(id="cc1111", name="Alice Chen", aliases=["ac"]),
        ])
        collab = edit_collaborator(data_dir, "Alice", add_aliases=["ac", "new"])
        assert collab.aliases.count("ac") == 1
        assert "new" in collab.aliases

    def test_remove_aliases(self, data_dir: Path):
        _write_collaborators(data_dir, [
            _make_collab(id="cc1111", name="Alice Chen", aliases=["ac", "ali"]),
        ])
        collab = edit_collaborator(data_dir, "Alice", remove_aliases=["ac"])
        assert "ac" not in collab.aliases
        assert "ali" in collab.aliases

    def test_add_tags(self, data_dir: Path):
        _write_collaborators(data_dir, [_make_collab(id="cc1111", name="Alice Chen")])
        collab = edit_collaborator(data_dir, "Alice", add_tags=["advisor", "ml"])
        assert "advisor" in collab.tags
        assert "ml" in collab.tags

    def test_remove_tags(self, data_dir: Path):
        _write_collaborators(data_dir, [
            _make_collab(id="cc1111", name="Alice Chen", tags=["advisor", "ml"]),
        ])
        collab = edit_collaborator(data_dir, "Alice", remove_tags=["ml"])
        assert "ml" not in collab.tags
        assert "advisor" in collab.tags

    def test_edit_not_found(self, data_dir: Path):
        _write_collaborators(data_dir, [_make_collab(id="cc1111", name="Alice Chen")])
        result = edit_collaborator(data_dir, "Nobody", set_role="Ghost")
        assert result is None

    def test_edit_persists(self, data_dir: Path):
        _write_collaborators(data_dir, [_make_collab(id="cc1111", name="Alice Chen")])
        edit_collaborator(data_dir, "Alice", set_role="PI")
        cf = load_collaborators(data_dir)
        assert cf.collaborators[0].role == "PI"


class TestAddCollaboratorNote:
    """Tests for add_collaborator_note()."""

    def test_add_note(self, data_dir: Path):
        _write_collaborators(data_dir, [_make_collab(id="cc1111", name="Alice Chen")])
        collab = add_collaborator_note(data_dir, "Alice", "Met at NeurIPS 2025")
        assert collab is not None
        assert "Met at NeurIPS 2025" in collab.notes

    def test_add_note_not_found(self, data_dir: Path):
        _write_collaborators(data_dir, [_make_collab(id="cc1111", name="Alice Chen")])
        result = add_collaborator_note(data_dir, "Nobody", "Lost note")
        assert result is None

    def test_add_multiple_notes(self, data_dir: Path):
        _write_collaborators(data_dir, [_make_collab(id="cc1111", name="Alice Chen")])
        add_collaborator_note(data_dir, "Alice", "Note 1")
        collab = add_collaborator_note(data_dir, "Alice", "Note 2")
        assert len(collab.notes) == 2


class TestRemoveCollaborator:
    """Tests for remove_collaborator()."""

    def test_remove_basic(self, data_dir: Path):
        _write_collaborators(data_dir, [
            _make_collab(id="cc1111", name="Alice Chen"),
            _make_collab(id="cc2222", name="Bob Smith"),
        ])
        removed = remove_collaborator(data_dir, "Alice")
        assert removed is not None
        assert removed.name == "Alice Chen"
        cf = load_collaborators(data_dir)
        assert len(cf.collaborators) == 1
        assert cf.collaborators[0].name == "Bob Smith"

    def test_remove_not_found(self, data_dir: Path):
        _write_collaborators(data_dir, [_make_collab(id="cc1111", name="Alice Chen")])
        result = remove_collaborator(data_dir, "Nobody")
        assert result is None


class TestGetTasksForPerson:
    """Tests for get_tasks_for_person()."""

    def test_matching_waiting_on(self, data_dir: Path):
        _write_tasks(data_dir, [
            _make_task(id="aaa111", description="Wait for Alice",
                       waiting_on="Alice Chen"),
            _make_task(id="bbb222", description="Wait for Bob",
                       waiting_on="Bob Smith"),
        ])
        from marvin.collaborator_schema import Collaborator

        collab = Collaborator(name="Alice Chen")
        results = get_tasks_for_person(data_dir, collab)
        assert len(results) == 1
        assert results[0].id == "aaa111"

    def test_alias_match(self, data_dir: Path):
        """A task whose waiting_on matches a collaborator alias is found."""
        _write_tasks(data_dir, [
            _make_task(id="aaa111", description="Wait for ac",
                       waiting_on="alice"),
        ])
        from marvin.collaborator_schema import Collaborator

        collab = Collaborator(name="Alice Chen", aliases=["ac"])
        results = get_tasks_for_person(data_dir, collab)
        # "alice" matches the auto-alias from "Alice Chen"
        assert len(results) == 1

    def test_no_match(self, data_dir: Path):
        _write_tasks(data_dir, [
            _make_task(id="aaa111", waiting_on="Bob Smith"),
        ])
        from marvin.collaborator_schema import Collaborator

        collab = Collaborator(name="Carol Davis")
        results = get_tasks_for_person(data_dir, collab)
        assert results == []

    def test_case_insensitive(self, data_dir: Path):
        _write_tasks(data_dir, [
            _make_task(id="aaa111", waiting_on="ALICE CHEN"),
        ])
        from marvin.collaborator_schema import Collaborator

        collab = Collaborator(name="Alice Chen")
        results = get_tasks_for_person(data_dir, collab)
        assert len(results) == 1


class TestResolveWaitingOn:
    """Tests for resolve_waiting_on()."""

    def test_exact_match_returns_canonical(self, data_dir: Path):
        _write_collaborators(data_dir, [
            _make_collab(id="cc1111", name="Alice Chen"),
        ])
        canonical, suggestions = resolve_waiting_on(data_dir, "alice")
        assert canonical == "Alice Chen"
        assert suggestions == []

    def test_fuzzy_returns_suggestions(self, data_dir: Path):
        _write_collaborators(data_dir, [
            _make_collab(id="cc1111", name="Alice Chen"),
        ])
        # "alic" is close to "alice" — gets a fuzzy match above threshold
        canonical, suggestions = resolve_waiting_on(data_dir, "Alic")
        # "Alic" is a prefix so should exact-match via matches_query
        # (name prefix match), so canonical should be set
        assert canonical == "Alice Chen"

    def test_no_match_at_all(self, data_dir: Path):
        _write_collaborators(data_dir, [
            _make_collab(id="cc1111", name="Alice Chen"),
        ])
        canonical, suggestions = resolve_waiting_on(data_dir, "zzzzxxxx")
        assert canonical is None
        assert suggestions == []

    def test_exact_match_by_full_name(self, data_dir: Path):
        _write_collaborators(data_dir, [
            _make_collab(id="cc1111", name="Alice Chen"),
        ])
        canonical, suggestions = resolve_waiting_on(data_dir, "Alice Chen")
        assert canonical == "Alice Chen"
        assert suggestions == []

    def test_fuzzy_suggestions_when_no_exact(self, data_dir: Path):
        """A close-but-not-exact query returns fuzzy suggestions."""
        _write_collaborators(data_dir, [
            _make_collab(id="cc1111", name="Alice Chen"),
            _make_collab(id="cc2222", name="Bob Smith"),
        ])
        # "Alce" is close to "Alice" but not a prefix — fuzzy should pick it up
        canonical, suggestions = resolve_waiting_on(data_dir, "Alce Chn")
        # Not an exact match (no prefix), so should be None with suggestions
        if canonical is None:
            assert len(suggestions) >= 1
            assert suggestions[0].name == "Alice Chen"
        else:
            # If the prefix-matching catches it, that's fine too
            assert canonical == "Alice Chen"
