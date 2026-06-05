"""Tests for idea-related functions in fast_path.py."""

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from marvin.idea_schema import (
    SPARK_DECAY_DAYS,
    DEVELOPING_DECAY_DAYS,
    Idea,
    IdeaFile,
    IdeaNote,
    save_idea_file,
)
from marvin import fast_path


def _write_ideas(data_dir: Path, ideas: list[dict]) -> None:
    """Write ideas to ideas.json."""
    path = data_dir / "ideas.json"
    path.write_text(json.dumps({"ideas": ideas}))


def _make_idea(**overrides) -> dict:
    """Create a minimal idea dict with overrides."""
    defaults = {
        "id": "abc123",
        "thought": "test idea",
        "status": "spark",
        "tags": [],
        "notes": [],
        "people": [],
        "links": [],
        "related_task_ids": [],
        "related_idea_ids": [],
        "created_at": date.today().isoformat(),
    }
    defaults.update(overrides)
    return defaults


class TestLoadSaveIdeas:
    """Test loading and saving ideas."""

    def test_load_empty(self, data_dir):
        idea_file = fast_path.load_ideas(data_dir)
        assert idea_file.ideas == []

    def test_load_missing_file(self, tmp_path):
        idea_file = fast_path.load_ideas(tmp_path)
        assert idea_file.ideas == []

    def test_save_and_load(self, data_dir):
        idea = Idea(thought="saved idea", tags=["ml"])
        idea_file = IdeaFile(ideas=[idea])
        fast_path.save_ideas(data_dir, idea_file)

        loaded = fast_path.load_ideas(data_dir)
        assert len(loaded.ideas) == 1
        assert loaded.ideas[0].thought == "saved idea"


class TestAddIdea:
    """Test adding ideas."""

    def test_add_basic(self, data_dir):
        idea = fast_path.add_idea(data_dir, "new idea")
        assert idea.thought == "new idea"
        assert idea.status == "spark"
        assert idea.created_at == date.today()

        # Verify persisted
        loaded = fast_path.load_ideas(data_dir)
        assert len(loaded.ideas) == 1

    def test_add_with_metadata(self, data_dir):
        idea = fast_path.add_idea(
            data_dir,
            "tagged idea",
            tags=["ml", "nlp"],
            source="paper",
            people=["Alice"],
            links=["https://example.com"],
        )
        assert idea.tags == ["ml", "nlp"]
        assert idea.source == "paper"
        assert idea.people == ["Alice"]
        assert idea.links == ["https://example.com"]

    def test_add_strips_hash_from_tags(self, data_dir):
        idea = fast_path.add_idea(
            data_dir, "tagged", tags=["#ml", "#nlp"],
        )
        assert idea.tags == ["ml", "nlp"]

    def test_add_multiple(self, data_dir):
        fast_path.add_idea(data_dir, "first")
        fast_path.add_idea(data_dir, "second")
        loaded = fast_path.load_ideas(data_dir)
        assert len(loaded.ideas) == 2


class TestFindIdeaById:
    """Test finding ideas by ID prefix."""

    def test_find_by_full_id(self, data_dir):
        idea = fast_path.add_idea(data_dir, "target")
        result = fast_path.find_idea_by_id(data_dir, idea.id)
        assert result is not None
        _, _, found = result
        assert found.thought == "target"

    def test_find_by_prefix(self, data_dir):
        idea = fast_path.add_idea(data_dir, "target")
        result = fast_path.find_idea_by_id(data_dir, idea.id[:4])
        assert result is not None

    def test_not_found(self, data_dir):
        fast_path.add_idea(data_dir, "other")
        assert fast_path.find_idea_by_id(data_dir, "zzzzzz") is None


class TestAddIdeaNote:
    """Test adding notes to ideas."""

    def test_add_note(self, data_dir):
        idea = fast_path.add_idea(data_dir, "noted idea")
        result = fast_path.add_idea_note(data_dir, idea.id, "a note")
        assert result is not None
        assert len(result.notes) == 1
        assert result.notes[0].text == "a note"
        assert result.last_tended_at == date.today()

    def test_add_note_not_found(self, data_dir):
        assert fast_path.add_idea_note(data_dir, "zzzzzz", "note") is None

    def test_note_persisted(self, data_dir):
        idea = fast_path.add_idea(data_dir, "noted")
        fast_path.add_idea_note(data_dir, idea.id, "persisted note")
        loaded = fast_path.load_ideas(data_dir)
        assert len(loaded.ideas[0].notes) == 1


class TestEditIdea:
    """Test editing idea metadata."""

    def test_add_tags(self, data_dir):
        idea = fast_path.add_idea(data_dir, "editable")
        result = fast_path.edit_idea(data_dir, idea.id, add_tags=["new-tag"])
        assert result is not None
        assert "new-tag" in result.tags

    def test_remove_tags(self, data_dir):
        idea = fast_path.add_idea(data_dir, "tagged", tags=["ml", "nlp"])
        result = fast_path.edit_idea(data_dir, idea.id, remove_tags=["ml"])
        assert result is not None
        assert "ml" not in result.tags
        assert "nlp" in result.tags

    def test_not_found(self, data_dir):
        assert fast_path.edit_idea(data_dir, "zzzzzz", add_tags=["x"]) is None


class TestDevelopIdea:
    """Test spark → developing transition."""

    def test_develop_spark(self, data_dir):
        idea = fast_path.add_idea(data_dir, "sparkly")
        result = fast_path.develop_idea(data_dir, idea.id, "worth keeping")
        assert result is not None
        assert result.status == "developing"
        assert len(result.notes) == 1
        assert result.last_tended_at == date.today()

    def test_develop_non_spark_returns_none(self, data_dir):
        idea = fast_path.add_idea(data_dir, "already dev")
        # First develop it
        fast_path.develop_idea(data_dir, idea.id, "developing")
        # Try to develop again
        result = fast_path.develop_idea(data_dir, idea.id, "again")
        assert result is None

    def test_develop_not_found(self, data_dir):
        assert fast_path.develop_idea(data_dir, "zzzzzz", "note") is None


class TestMatureIdea:
    """Test developing → mature transition."""

    def test_mature_developing(self, data_dir):
        idea = fast_path.add_idea(data_dir, "growing")
        fast_path.develop_idea(data_dir, idea.id, "developing")
        result = fast_path.mature_idea(data_dir, idea.id, "ready to become a project")
        assert result is not None
        assert result.status == "mature"
        assert len(result.notes) == 2  # develop note + mature note

    def test_mature_spark_returns_none(self, data_dir):
        idea = fast_path.add_idea(data_dir, "too young")
        result = fast_path.mature_idea(data_dir, idea.id, "not ready")
        assert result is None


class TestPromoteIdea:
    """Test idea → task promotion."""

    def test_promote_creates_task(self, data_dir):
        idea = fast_path.add_idea(data_dir, "promotable", tags=["ml"])
        result = fast_path.promote_idea(data_dir, idea.id)
        assert result is not None
        promoted_idea, task = result

        # Check the idea
        assert promoted_idea.status == "archived"
        assert promoted_idea.promoted_to == task.id
        assert promoted_idea.archive_reason == "promoted"

        # Check the task
        assert task.description == "promotable"
        assert "ml" in task.tags

        # Verify task persisted
        tf = fast_path.load_tasks(data_dir)
        assert len(tf.tasks) == 1

    def test_promote_with_deadline(self, data_dir):
        idea = fast_path.add_idea(data_dir, "deadline idea")
        result = fast_path.promote_idea(data_dir, idea.id, deadline="2026-09-01")
        assert result is not None
        _, task = result
        assert task.deadline == date(2026, 9, 1)

    def test_promote_archived_returns_none(self, data_dir):
        idea = fast_path.add_idea(data_dir, "archived")
        fast_path.archive_idea(data_dir, idea.id)
        result = fast_path.promote_idea(data_dir, idea.id)
        assert result is None


class TestArchiveIdea:
    """Test manual archival."""

    def test_archive(self, data_dir):
        idea = fast_path.add_idea(data_dir, "archivable")
        result = fast_path.archive_idea(data_dir, idea.id)
        assert result is not None
        assert result.status == "archived"
        assert result.archived_at == date.today()
        assert result.archive_reason == "manual"

    def test_archive_not_found(self, data_dir):
        assert fast_path.archive_idea(data_dir, "zzzzzz") is None


class TestRemoveIdea:
    """Test permanent removal."""

    def test_remove(self, data_dir):
        idea = fast_path.add_idea(data_dir, "removable")
        removed = fast_path.remove_idea(data_dir, idea.id)
        assert removed is not None
        assert removed.thought == "removable"

        loaded = fast_path.load_ideas(data_dir)
        assert len(loaded.ideas) == 0

    def test_remove_not_found(self, data_dir):
        assert fast_path.remove_idea(data_dir, "zzzzzz") is None


class TestRunIdeaDecay:
    """Test the auto-archive decay mechanism."""

    def test_no_decay_for_fresh_ideas(self, data_dir):
        fast_path.add_idea(data_dir, "fresh")
        archived, warning = fast_path.run_idea_decay(data_dir)
        assert len(archived) == 0

    def test_archives_expired_sparks(self, data_dir):
        _write_ideas(data_dir, [
            _make_idea(
                id="exp123",
                thought="expired",
                created_at=(date.today() - timedelta(days=SPARK_DECAY_DAYS + 5)).isoformat(),
            ),
        ])

        archived, warning = fast_path.run_idea_decay(data_dir)
        assert len(archived) == 1
        assert archived[0].thought == "expired"
        assert archived[0].archive_reason == "auto-decay"

        # Verify persisted
        loaded = fast_path.load_ideas(data_dir)
        assert loaded.ideas[0].status == "archived"

    def test_warns_about_expiring_sparks(self, data_dir):
        days_until_warning = SPARK_DECAY_DAYS - 5  # 5 days left, within warning window
        _write_ideas(data_dir, [
            _make_idea(
                id="warn12",
                thought="warning",
                created_at=(date.today() - timedelta(days=days_until_warning)).isoformat(),
            ),
        ])

        archived, warning = fast_path.run_idea_decay(data_dir)
        assert len(archived) == 0
        assert len(warning) == 1

    def test_no_decay_for_mature(self, data_dir):
        _write_ideas(data_dir, [
            _make_idea(
                id="mat123",
                thought="mature",
                status="mature",
                created_at=(date.today() - timedelta(days=365)).isoformat(),
            ),
        ])

        archived, warning = fast_path.run_idea_decay(data_dir)
        assert len(archived) == 0
        assert len(warning) == 0


class TestSearchIdeas:
    """Test idea search functionality."""

    def test_search_by_thought(self, data_dir):
        fast_path.add_idea(data_dir, "contrastive pretraining approach")
        fast_path.add_idea(data_dir, "annotation tool for lab")

        results = fast_path.search_ideas_by_query(data_dir, "contrastive")
        assert len(results) == 1
        assert results[0].thought == "contrastive pretraining approach"

    def test_search_by_tag(self, data_dir):
        fast_path.add_idea(data_dir, "idea one", tags=["ml"])
        fast_path.add_idea(data_dir, "idea two", tags=["nlp"])

        results = fast_path.search_ideas_by_query(data_dir, "ml")
        assert len(results) == 1

    def test_search_case_insensitive(self, data_dir):
        fast_path.add_idea(data_dir, "Machine Learning idea")
        results = fast_path.search_ideas_by_query(data_dir, "machine learning")
        assert len(results) == 1

    def test_search_no_results(self, data_dir):
        fast_path.add_idea(data_dir, "something")
        results = fast_path.search_ideas_by_query(data_dir, "nonexistent")
        assert len(results) == 0


class TestGetIdeaStats:
    """Test idea statistics."""

    def test_empty_stats(self, data_dir):
        stats = fast_path.get_idea_stats(data_dir)
        assert stats["total"] == 0
        assert stats["sparks"] == 0

    def test_mixed_stats(self, data_dir):
        fast_path.add_idea(data_dir, "spark1")
        fast_path.add_idea(data_dir, "spark2")
        idea3 = fast_path.add_idea(data_dir, "to develop")
        fast_path.develop_idea(data_dir, idea3.id, "developing")

        stats = fast_path.get_idea_stats(data_dir)
        assert stats["sparks"] == 2
        assert stats["developing"] == 1
        assert stats["total"] == 3


class TestLinkIdea:
    """Test cross-linking ideas."""

    def test_link_url(self, data_dir):
        idea = fast_path.add_idea(data_dir, "linkable")
        result = fast_path.link_idea(
            data_dir, idea.id, url="https://example.com",
        )
        assert result is not None
        assert "https://example.com" in result.links

    def test_link_person(self, data_dir):
        idea = fast_path.add_idea(data_dir, "linked to person")
        result = fast_path.link_idea(data_dir, idea.id, person="Alice")
        assert result is not None
        assert "Alice" in result.people

    def test_link_deduplicates(self, data_dir):
        idea = fast_path.add_idea(data_dir, "dedup")
        fast_path.link_idea(data_dir, idea.id, url="https://example.com")
        result = fast_path.link_idea(data_dir, idea.id, url="https://example.com")
        assert result is not None
        assert result.links.count("https://example.com") == 1
