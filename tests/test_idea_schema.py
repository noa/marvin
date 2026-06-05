"""Tests for idea_schema.py — Pydantic models, decay logic, and I/O."""

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from marvin.idea_schema import (
    DEVELOPING_DECAY_DAYS,
    DEVELOPING_WARNING_DAYS,
    SPARK_DECAY_DAYS,
    SPARK_WARNING_DAYS,
    Idea,
    IdeaFile,
    IdeaNote,
    load_idea_file,
    save_idea_file,
)


class TestIdeaDefaults:
    """Test Idea model creation with defaults."""

    def test_minimal_creation(self):
        idea = Idea(thought="test idea")
        assert idea.thought == "test idea"
        assert idea.status == "spark"
        assert idea.tags == []
        assert idea.notes == []
        assert idea.people == []
        assert idea.links == []
        assert idea.source is None
        assert idea.promoted_to is None
        assert idea.created_at == date.today()
        assert idea.last_tended_at is None
        assert idea.archived_at is None
        assert idea.archive_reason is None
        assert len(idea.id) == 6

    def test_full_creation(self):
        idea = Idea(
            thought="full idea",
            status="developing",
            tags=["ml", "nlp"],
            source="paper",
            people=["Alice"],
            links=["https://arxiv.org"],
            related_task_ids=["abc123"],
            related_idea_ids=["def456"],
        )
        assert idea.status == "developing"
        assert idea.tags == ["ml", "nlp"]
        assert idea.people == ["Alice"]

    def test_unique_ids(self):
        ids = {Idea(thought=f"idea {i}").id for i in range(20)}
        assert len(ids) == 20


class TestIdeaNote:
    """Test IdeaNote model."""

    def test_note_defaults(self):
        note = IdeaNote(text="some thought")
        assert note.text == "some thought"
        assert note.added_at == date.today()

    def test_note_with_date(self):
        d = date(2026, 1, 15)
        note = IdeaNote(text="old thought", added_at=d)
        assert note.added_at == d


class TestDecayLogic:
    """Test the decay clock, warnings, and expiry."""

    def _make_idea(self, status="spark", age_days=0, tended_days_ago=None):
        """Helper: create an idea with controlled age."""
        idea = Idea(
            thought="test",
            status=status,
            created_at=date.today() - timedelta(days=age_days),
        )
        if tended_days_ago is not None:
            idea.last_tended_at = date.today() - timedelta(days=tended_days_ago)
        return idea

    # --- days_until_archive ---

    def test_spark_fresh(self):
        idea = self._make_idea("spark", age_days=0)
        assert idea.days_until_archive() == SPARK_DECAY_DAYS

    def test_spark_halfway(self):
        idea = self._make_idea("spark", age_days=15)
        assert idea.days_until_archive() == SPARK_DECAY_DAYS - 15

    def test_spark_expired(self):
        idea = self._make_idea("spark", age_days=35)
        assert idea.days_until_archive() == 0

    def test_developing_fresh(self):
        idea = self._make_idea("developing", age_days=0)
        assert idea.days_until_archive() == DEVELOPING_DECAY_DAYS

    def test_developing_expired(self):
        idea = self._make_idea("developing", age_days=100)
        assert idea.days_until_archive() == 0

    def test_mature_no_decay(self):
        idea = self._make_idea("mature", age_days=365)
        assert idea.days_until_archive() is None

    def test_archived_no_decay(self):
        idea = Idea(thought="test", status="archived")
        assert idea.days_until_archive() is None

    def test_promoted_no_decay(self):
        idea = Idea(thought="test", status="promoted")
        assert idea.days_until_archive() is None

    def test_tended_resets_clock(self):
        idea = self._make_idea("spark", age_days=25, tended_days_ago=5)
        # Decay anchor is last_tended_at (5 days ago), not created_at (25 days ago)
        assert idea.days_until_archive() == SPARK_DECAY_DAYS - 5

    # --- is_warning ---

    def test_spark_not_warning_early(self):
        idea = self._make_idea("spark", age_days=10)
        assert not idea.is_warning()

    def test_spark_warning_near_end(self):
        threshold = SPARK_DECAY_DAYS - SPARK_WARNING_DAYS
        idea = self._make_idea("spark", age_days=threshold)
        assert idea.is_warning()

    def test_spark_warning_last_day(self):
        idea = self._make_idea("spark", age_days=SPARK_DECAY_DAYS - 1)
        assert idea.is_warning()

    def test_developing_warning_near_end(self):
        threshold = DEVELOPING_DECAY_DAYS - DEVELOPING_WARNING_DAYS
        idea = self._make_idea("developing", age_days=threshold)
        assert idea.is_warning()

    def test_developing_not_warning_early(self):
        idea = self._make_idea("developing", age_days=30)
        assert not idea.is_warning()

    def test_mature_never_warning(self):
        idea = self._make_idea("mature", age_days=365)
        assert not idea.is_warning()

    # --- is_expired ---

    def test_spark_not_expired_early(self):
        idea = self._make_idea("spark", age_days=15)
        assert not idea.is_expired()

    def test_spark_expired_at_boundary(self):
        idea = self._make_idea("spark", age_days=SPARK_DECAY_DAYS)
        assert idea.is_expired()

    def test_spark_expired_past_boundary(self):
        idea = self._make_idea("spark", age_days=SPARK_DECAY_DAYS + 10)
        assert idea.is_expired()

    def test_mature_never_expires(self):
        idea = self._make_idea("mature", age_days=999)
        assert not idea.is_expired()

    # --- tend ---

    def test_tend_adds_note_and_resets(self):
        idea = self._make_idea("spark", age_days=20)
        assert idea.last_tended_at is None
        assert len(idea.notes) == 0

        idea.tend("still relevant")

        assert len(idea.notes) == 1
        assert idea.notes[0].text == "still relevant"
        assert idea.notes[0].added_at == date.today()
        assert idea.last_tended_at == date.today()
        # Decay clock should now be reset
        assert idea.days_until_archive() == SPARK_DECAY_DAYS


class TestIdeaFile:
    """Test IdeaFile container."""

    def _make_file(self, ideas):
        return IdeaFile(ideas=ideas)

    def test_empty(self):
        f = IdeaFile()
        assert f.ideas == []
        assert f.active_ideas == []
        assert f.sparks == []

    def test_active_ideas_excludes_archived(self):
        f = self._make_file([
            Idea(thought="a", status="spark"),
            Idea(thought="b", status="archived"),
            Idea(thought="c", status="promoted"),
            Idea(thought="d", status="developing"),
        ])
        assert len(f.active_ideas) == 2
        assert {i.thought for i in f.active_ideas} == {"a", "d"}

    def test_status_filters(self):
        f = self._make_file([
            Idea(thought="a", status="spark"),
            Idea(thought="b", status="spark"),
            Idea(thought="c", status="developing"),
            Idea(thought="d", status="mature"),
        ])
        assert len(f.sparks) == 2
        assert len(f.developing_ideas) == 1
        assert len(f.mature_ideas) == 1

    def test_find_by_id_full(self):
        idea = Idea(thought="target")
        f = self._make_file([Idea(thought="other"), idea])
        assert f.find_by_id(idea.id) is idea

    def test_find_by_id_prefix(self):
        idea = Idea(thought="target")
        f = self._make_file([idea])
        assert f.find_by_id(idea.id[:4]) is idea

    def test_find_by_id_case_insensitive(self):
        idea = Idea(thought="target")
        f = self._make_file([idea])
        assert f.find_by_id(idea.id[:4].upper()) is idea

    def test_find_by_id_not_found(self):
        f = self._make_file([Idea(thought="a")])
        assert f.find_by_id("zzzzz") is None

    def test_expiring_ideas(self):
        old_spark = Idea(
            thought="old",
            status="spark",
            created_at=date.today() - timedelta(days=SPARK_DECAY_DAYS - 3),
        )
        fresh_spark = Idea(thought="fresh", status="spark")
        mature = Idea(thought="safe", status="mature")

        f = self._make_file([old_spark, fresh_spark, mature])
        expiring = f.expiring_ideas()
        assert len(expiring) == 1
        assert expiring[0].thought == "old"

    def test_expired_ideas(self):
        expired = Idea(
            thought="dead",
            status="spark",
            created_at=date.today() - timedelta(days=SPARK_DECAY_DAYS + 5),
        )
        alive = Idea(thought="alive", status="spark")
        f = self._make_file([expired, alive])
        assert len(f.expired_ideas()) == 1
        assert f.expired_ideas()[0].thought == "dead"


class TestIdeaFileIO:
    """Test load/save round-trips."""

    def test_save_and_load(self, tmp_path):
        path = tmp_path / "ideas.json"
        idea = Idea(thought="test idea", tags=["ml"])
        idea_file = IdeaFile(ideas=[idea])

        save_idea_file(idea_file, path)

        loaded = load_idea_file(path)
        assert len(loaded.ideas) == 1
        assert loaded.ideas[0].thought == "test idea"
        assert loaded.ideas[0].tags == ["ml"]
        assert loaded.ideas[0].id == idea.id

    def test_load_missing_file(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        loaded = load_idea_file(path)
        assert loaded.ideas == []

    def test_load_empty_file(self, tmp_path):
        path = tmp_path / "ideas.json"
        path.write_text("")
        loaded = load_idea_file(path)
        assert loaded.ideas == []

    def test_round_trip_with_notes(self, tmp_path):
        path = tmp_path / "ideas.json"
        idea = Idea(thought="noted idea")
        idea.tend("first note")
        idea.tend("second note")

        save_idea_file(IdeaFile(ideas=[idea]), path)
        loaded = load_idea_file(path)

        assert len(loaded.ideas[0].notes) == 2
        assert loaded.ideas[0].notes[0].text == "first note"
        assert loaded.ideas[0].last_tended_at == date.today()

    def test_json_format(self, tmp_path):
        path = tmp_path / "ideas.json"
        save_idea_file(IdeaFile(ideas=[Idea(thought="pretty")]), path)
        content = path.read_text()
        # Should be indented JSON
        parsed = json.loads(content)
        assert "ideas" in parsed
        assert len(parsed["ideas"]) == 1
