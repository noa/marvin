"""Tests for marvin.task_schema module."""

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from marvin.task_schema import (
    Task,
    TaskFile,
    generate_task_id,
    load_task_file,
    save_task_file,
    validate_all_task_files,
    validate_json_file,
)


# ---------------------------------------------------------------------------
# Task model creation
# ---------------------------------------------------------------------------

class TestTaskCreation:
    """Tests for Task model instantiation and defaults."""

    def test_create_minimal(self):
        """Only description is required; all else gets defaults."""
        t = Task(description="Write abstract")
        assert t.description == "Write abstract"
        assert t.status == "open"
        assert t.priority == "medium"
        assert t.deadline is None
        assert t.waiting_on is None
        assert t.tags == []
        assert t.notes == []
        assert t.parent_id is None
        assert t.completed_at is None
        assert t.created_at == date.today()
        assert len(t.id) == 6  # hex id

    def test_create_with_all_fields(self, sample_task):
        """Create a task with explicit values."""
        t = Task(**sample_task)
        assert t.description == sample_task["description"]
        assert t.deadline == date(2026, 7, 1)
        assert t.waiting_on == "Dr. Smith"
        assert t.priority == "high"
        assert t.tags == ["writing", "review"]

    def test_generate_task_id_uniqueness(self):
        """IDs should be unique across many calls."""
        ids = {generate_task_id() for _ in range(200)}
        assert len(ids) == 200

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            Task(description="x", status="archived")

    def test_invalid_priority_rejected(self):
        with pytest.raises(ValidationError):
            Task(description="x", priority="urgent")

    def test_unicode_description(self):
        t = Task(description="Revise résumé — final draft 📄")
        assert "résumé" in t.description


# ---------------------------------------------------------------------------
# Task.is_overdue
# ---------------------------------------------------------------------------

class TestTaskIsOverdue:

    def test_done_task_not_overdue(self):
        t = Task(description="x", status="done", deadline=date.today() - timedelta(days=10))
        assert t.is_overdue() is False

    def test_future_deadline_not_overdue(self):
        t = Task(description="x", deadline=date.today() + timedelta(days=5))
        assert t.is_overdue() is False

    def test_past_deadline_is_overdue(self):
        t = Task(description="x", deadline=date.today() - timedelta(days=1))
        assert t.is_overdue() is True

    def test_today_deadline_not_overdue(self):
        """Deadline == today means NOT overdue (due today, not past)."""
        t = Task(description="x", deadline=date.today())
        assert t.is_overdue() is False

    def test_no_deadline_not_overdue(self):
        t = Task(description="x")
        assert t.is_overdue() is False


# ---------------------------------------------------------------------------
# Task.is_due_within
# ---------------------------------------------------------------------------

class TestTaskIsDueWithin:

    def test_due_today_within_zero_days(self):
        t = Task(description="x", deadline=date.today())
        assert t.is_due_within(0) is True

    def test_due_tomorrow_within_one_day(self):
        t = Task(description="x", deadline=date.today() + timedelta(days=1))
        assert t.is_due_within(1) is True

    def test_due_tomorrow_not_within_zero_days(self):
        t = Task(description="x", deadline=date.today() + timedelta(days=1))
        assert t.is_due_within(0) is False

    def test_past_deadline_not_due_within(self):
        t = Task(description="x", deadline=date.today() - timedelta(days=1))
        assert t.is_due_within(7) is False

    def test_done_task_not_due_within(self):
        t = Task(description="x", status="done", deadline=date.today())
        assert t.is_due_within(7) is False

    def test_no_deadline_not_due_within(self):
        t = Task(description="x")
        assert t.is_due_within(30) is False

    def test_boundary_exact_days(self):
        t = Task(description="x", deadline=date.today() + timedelta(days=5))
        assert t.is_due_within(5) is True
        assert t.is_due_within(4) is False


# ---------------------------------------------------------------------------
# TaskFile properties
# ---------------------------------------------------------------------------

class TestTaskFileProperties:

    def _make_file(self, tasks):
        return TaskFile(project="test", tasks=tasks)

    def test_open_tasks(self):
        tf = self._make_file([
            Task(description="a"),
            Task(description="b", status="done"),
            Task(description="c"),
        ])
        assert len(tf.open_tasks) == 2

    def test_open_count(self):
        tf = self._make_file([Task(description="a"), Task(description="b")])
        assert tf.open_count == 2

    def test_open_count_empty(self):
        tf = self._make_file([])
        assert tf.open_count == 0

    def test_waiting_count(self):
        tf = self._make_file([
            Task(description="a", waiting_on="Bob"),
            Task(description="b"),
            Task(description="c", waiting_on="Eve", status="done"),  # done, shouldn't count
        ])
        assert tf.waiting_count == 1

    def test_overdue_count(self):
        tf = self._make_file([
            Task(description="a", deadline=date.today() - timedelta(days=3)),
            Task(description="b", deadline=date.today() + timedelta(days=3)),
            Task(description="c", deadline=date.today() - timedelta(days=1), status="done"),
        ])
        assert tf.overdue_count == 1

    def test_next_deadline_picks_earliest(self):
        tf = self._make_file([
            Task(description="a", deadline=date.today() + timedelta(days=10)),
            Task(description="b", deadline=date.today() + timedelta(days=2)),
            Task(description="c", deadline=date.today() + timedelta(days=5)),
        ])
        assert tf.next_deadline == date.today() + timedelta(days=2)

    def test_next_deadline_skips_past(self):
        tf = self._make_file([
            Task(description="a", deadline=date.today() - timedelta(days=1)),
        ])
        assert tf.next_deadline is None

    def test_next_deadline_none_when_empty(self):
        tf = self._make_file([])
        assert tf.next_deadline is None

    def test_next_deadline_includes_today(self):
        tf = self._make_file([
            Task(description="a", deadline=date.today()),
        ])
        assert tf.next_deadline == date.today()


# ---------------------------------------------------------------------------
# TaskFile hierarchy helpers
# ---------------------------------------------------------------------------

class TestTaskFileHierarchy:

    @pytest.fixture
    def hierarchical_file(self):
        parent = Task(id="parent", description="Parent task")
        child1 = Task(id="child1", description="Child 1", parent_id="parent")
        child2 = Task(id="child2", description="Child 2", parent_id="parent", status="done")
        grandchild = Task(id="gc1", description="Grandchild", parent_id="child1")
        orphan = Task(id="orphan", description="Orphan task")
        return TaskFile(project="test", tasks=[parent, child1, child2, grandchild, orphan])

    def test_get_task_by_id_found(self, hierarchical_file):
        t = hierarchical_file.get_task_by_id("child1")
        assert t is not None
        assert t.description == "Child 1"

    def test_get_task_by_id_not_found(self, hierarchical_file):
        assert hierarchical_file.get_task_by_id("nonexistent") is None

    def test_get_children(self, hierarchical_file):
        children = hierarchical_file.get_children("parent")
        assert len(children) == 2
        ids = {c.id for c in children}
        assert ids == {"child1", "child2"}

    def test_get_children_none(self, hierarchical_file):
        assert hierarchical_file.get_children("orphan") == []

    def test_get_root_tasks(self, hierarchical_file):
        roots = hierarchical_file.get_root_tasks()
        ids = {t.id for t in roots}
        assert ids == {"parent", "orphan"}

    def test_get_open_root_tasks(self, hierarchical_file):
        roots = hierarchical_file.get_open_root_tasks()
        ids = {t.id for t in roots}
        assert ids == {"parent", "orphan"}

    def test_get_subtree(self, hierarchical_file):
        tree = hierarchical_file.get_subtree("parent")
        ids = {t.id for t in tree}
        assert ids == {"parent", "child1", "child2", "gc1"}

    def test_get_subtree_leaf(self, hierarchical_file):
        tree = hierarchical_file.get_subtree("gc1")
        assert len(tree) == 1
        assert tree[0].id == "gc1"

    def test_get_subtree_nonexistent(self, hierarchical_file):
        assert hierarchical_file.get_subtree("nope") == []

    def test_has_open_subtasks_true(self, hierarchical_file):
        assert hierarchical_file.has_open_subtasks("parent") is True

    def test_has_open_subtasks_false_all_done(self):
        parent = Task(id="p", description="P")
        child = Task(id="c", description="C", parent_id="p", status="done")
        tf = TaskFile(project="t", tasks=[parent, child])
        assert tf.has_open_subtasks("p") is False

    def test_has_open_subtasks_no_children(self, hierarchical_file):
        assert hierarchical_file.has_open_subtasks("orphan") is False


# ---------------------------------------------------------------------------
# load_task_file / save_task_file round-trip
# ---------------------------------------------------------------------------

class TestTaskFileIO:

    def test_round_trip(self, data_dir):
        path = data_dir / "tasks.json"
        tf = load_task_file(path)
        assert tf.project == "default"
        assert tf.tasks == []

        # Add a task, save, reload
        tf.tasks.append(Task(id="aaa111", description="Test task"))
        save_task_file(tf, path)

        reloaded = load_task_file(path)
        assert reloaded.open_count == 1
        assert reloaded.tasks[0].description == "Test task"
        assert reloaded.tasks[0].id == "aaa111"

    def test_load_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_task_file(tmp_path / "nope.json")

    def test_save_creates_valid_json(self, tmp_path):
        path = tmp_path / "out.json"
        tf = TaskFile(project="p", tasks=[Task(description="d")])
        save_task_file(tf, path)
        raw = json.loads(path.read_text())
        assert raw["project"] == "p"
        assert len(raw["tasks"]) == 1


# ---------------------------------------------------------------------------
# validate_json_file
# ---------------------------------------------------------------------------

class TestValidateJsonFile:

    def test_valid_file(self, data_dir):
        is_valid, err = validate_json_file(data_dir / "tasks.json")
        assert is_valid is True
        assert err is None

    def test_invalid_json_syntax(self, tmp_path):
        path = tmp_path / "tasks.json"
        path.write_text("{bad json")
        is_valid, err = validate_json_file(path)
        assert is_valid is False
        assert "JSON" in err or "parse" in err.lower() or "Expecting" in err

    def test_invalid_schema(self, tmp_path):
        path = tmp_path / "tasks.json"
        path.write_text(json.dumps({"project": 123, "tasks": "not a list"}))
        is_valid, err = validate_json_file(path)
        assert is_valid is False

    def test_missing_file(self, tmp_path):
        is_valid, err = validate_json_file(tmp_path / "nope.json")
        assert is_valid is False
        assert err is not None


# ---------------------------------------------------------------------------
# validate_all_task_files
# ---------------------------------------------------------------------------

class TestValidateAllTaskFiles:

    def test_no_errors_when_valid(self, data_dir):
        errors = validate_all_task_files(data_dir)
        assert errors == []

    def test_errors_when_invalid(self, tmp_path):
        path = tmp_path / "tasks.json"
        path.write_text("not json at all")
        errors = validate_all_task_files(tmp_path)
        assert len(errors) == 1
        assert errors[0][0] == path

    def test_no_tasks_file_means_no_errors(self, tmp_path):
        """If tasks.json doesn't exist, nothing to validate → no errors."""
        errors = validate_all_task_files(tmp_path)
        assert errors == []
