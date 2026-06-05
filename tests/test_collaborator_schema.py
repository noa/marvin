"""Tests for marvin.collaborator_schema module."""

import json
from pathlib import Path

import pytest

from marvin.collaborator_schema import (
    Collaborator,
    CollaboratorFile,
    _auto_aliases,
    load_collaborator_file,
    resolve_person,
    save_collaborator_file,
)


# ---------------------------------------------------------------------------
# _auto_aliases
# ---------------------------------------------------------------------------

class TestAutoAliases:

    def test_single_word_name(self):
        assert _auto_aliases("Madonna") == ["madonna"]

    def test_two_word_name(self):
        aliases = _auto_aliases("Alice Chen")
        assert "alice" in aliases
        assert "chen" in aliases
        assert len(aliases) == 2

    def test_multi_word_name(self):
        aliases = _auto_aliases("Mary Jane Watson")
        assert aliases == ["mary", "jane", "watson"]

    def test_punctuation_stripped(self):
        aliases = _auto_aliases("Dr. Smith,")
        assert "dr" in aliases
        assert "smith" in aliases
        # No leftover punctuation
        for a in aliases:
            assert not a.endswith(".") and not a.endswith(",")

    def test_duplicated_parts(self):
        aliases = _auto_aliases("Bob Bob")
        assert aliases == ["bob"]

    def test_empty_string(self):
        assert _auto_aliases("") == []

    def test_case_insensitive(self):
        aliases = _auto_aliases("ALICE")
        assert aliases == ["alice"]


# ---------------------------------------------------------------------------
# Collaborator model creation
# ---------------------------------------------------------------------------

class TestCollaboratorCreation:

    def test_minimal(self):
        c = Collaborator(name="Bob Lee")
        assert c.name == "Bob Lee"
        assert c.role is None
        assert c.affiliation is None
        assert c.email is None
        assert c.aliases == []
        assert c.notes == []
        assert c.tags == []
        assert len(c.id) == 6

    def test_with_all_fields(self, sample_collaborator):
        c = Collaborator(**sample_collaborator)
        assert c.name == "Alice Chen"
        assert c.role == "PhD student"
        assert c.affiliation == "MIT CSAIL"
        assert c.email == "alice@mit.edu"

    def test_unicode_name(self):
        c = Collaborator(name="José García")
        assert c.name == "José García"


# ---------------------------------------------------------------------------
# Collaborator.all_aliases
# ---------------------------------------------------------------------------

class TestAllAliases:

    def test_combines_auto_and_explicit(self):
        c = Collaborator(name="Alice Chen", aliases=["AC", "alicec"])
        aa = c.all_aliases()
        assert "alice" in aa
        assert "chen" in aa
        assert "ac" in aa
        assert "alicec" in aa

    def test_deduplication(self):
        c = Collaborator(name="Alice Chen", aliases=["alice"])
        aa = c.all_aliases()
        assert aa.count("alice") == 1

    def test_sorted(self):
        c = Collaborator(name="Zara Adams", aliases=["z"])
        aa = c.all_aliases()
        assert aa == sorted(aa)


# ---------------------------------------------------------------------------
# Collaborator.matches_query
# ---------------------------------------------------------------------------

class TestMatchesQuery:

    @pytest.fixture
    def collab(self):
        return Collaborator(id="abc123", name="Alice Chen", aliases=["AC"])

    def test_exact_name(self, collab):
        assert collab.matches_query("Alice Chen") is True

    def test_exact_name_case_insensitive(self, collab):
        assert collab.matches_query("alice chen") is True

    def test_id_prefix(self, collab):
        assert collab.matches_query("abc") is True

    def test_id_full(self, collab):
        assert collab.matches_query("abc123") is True

    def test_alias_exact(self, collab):
        assert collab.matches_query("AC") is True

    def test_auto_alias_exact(self, collab):
        assert collab.matches_query("chen") is True

    def test_name_prefix(self, collab):
        assert collab.matches_query("alice") is True

    def test_alias_prefix(self, collab):
        assert collab.matches_query("ali") is True

    def test_no_match(self, collab):
        assert collab.matches_query("zzz") is False

    def test_whitespace_stripped(self, collab):
        assert collab.matches_query("  alice chen  ") is True


# ---------------------------------------------------------------------------
# Collaborator.similarity_score
# ---------------------------------------------------------------------------

class TestSimilarityScore:

    def test_high_for_exact_match(self):
        c = Collaborator(name="Alice Chen")
        assert c.similarity_score("alice chen") > 0.9

    def test_low_for_unrelated(self):
        c = Collaborator(name="Alice Chen")
        assert c.similarity_score("xyz") < 0.3

    def test_partial_match_moderate(self):
        c = Collaborator(name="Alice Chen")
        # "alic" is not an alias, so it should score moderately
        score = c.similarity_score("alic")
        assert 0.4 < score < 1.0

    def test_returns_float_in_range(self):
        c = Collaborator(name="Bob")
        s = c.similarity_score("bob")
        assert isinstance(s, float)
        assert 0.0 <= s <= 1.0


# ---------------------------------------------------------------------------
# CollaboratorFile.find_by_query
# ---------------------------------------------------------------------------

class TestFindByQuery:

    @pytest.fixture
    def cfile(self):
        return CollaboratorFile(collaborators=[
            Collaborator(id="aaa111", name="Alice Chen"),
            Collaborator(id="bbb222", name="Bob Smith"),
        ])

    def test_found(self, cfile):
        c = cfile.find_by_query("alice")
        assert c is not None
        assert c.name == "Alice Chen"

    def test_not_found(self, cfile):
        assert cfile.find_by_query("charlie") is None

    def test_by_id_prefix(self, cfile):
        c = cfile.find_by_query("bbb")
        assert c is not None
        assert c.name == "Bob Smith"


# ---------------------------------------------------------------------------
# CollaboratorFile.fuzzy_matches
# ---------------------------------------------------------------------------

class TestFuzzyMatches:

    @pytest.fixture
    def cfile(self):
        return CollaboratorFile(collaborators=[
            Collaborator(name="Alice Chen"),
            Collaborator(name="Alicia Chang"),
            Collaborator(name="Bob Smith"),
            Collaborator(name="Charlie Brown"),
        ])

    def test_above_threshold(self, cfile):
        matches = cfile.fuzzy_matches("alice", threshold=0.5)
        names = [m.name for m in matches]
        assert "Alice Chen" in names

    def test_below_threshold_excluded(self, cfile):
        matches = cfile.fuzzy_matches("alice", threshold=0.99)
        # Only extremely close matches should survive a 0.99 threshold
        # "alice chen" vs "alice" won't hit 0.99
        assert len(matches) <= 1

    def test_limit(self, cfile):
        matches = cfile.fuzzy_matches("a", threshold=0.0, limit=2)
        assert len(matches) <= 2

    def test_sorted_by_score(self, cfile):
        matches = cfile.fuzzy_matches("alice", threshold=0.3)
        if len(matches) >= 2:
            scores = [m.similarity_score("alice") for m in matches]
            assert scores == sorted(scores, reverse=True)

    def test_empty_collaborators(self):
        cf = CollaboratorFile(collaborators=[])
        assert cf.fuzzy_matches("alice") == []


# ---------------------------------------------------------------------------
# load_collaborator_file / save_collaborator_file round-trip
# ---------------------------------------------------------------------------

class TestCollaboratorFileIO:

    def test_round_trip(self, data_dir):
        path = data_dir / "collaborators.json"
        cf = load_collaborator_file(path)
        assert cf.collaborators == []

        cf.collaborators.append(Collaborator(id="aaa111", name="Test User"))
        save_collaborator_file(cf, path)

        reloaded = load_collaborator_file(path)
        assert len(reloaded.collaborators) == 1
        assert reloaded.collaborators[0].name == "Test User"

    def test_missing_file_returns_empty(self, tmp_path):
        cf = load_collaborator_file(tmp_path / "nope.json")
        assert cf.collaborators == []

    def test_empty_file_returns_empty(self, tmp_path):
        path = tmp_path / "collaborators.json"
        path.write_text("")
        cf = load_collaborator_file(path)
        assert cf.collaborators == []

    def test_whitespace_only_file_returns_empty(self, tmp_path):
        path = tmp_path / "collaborators.json"
        path.write_text("   \n  ")
        cf = load_collaborator_file(path)
        assert cf.collaborators == []

    def test_save_produces_valid_json(self, tmp_path):
        path = tmp_path / "out.json"
        cf = CollaboratorFile(collaborators=[Collaborator(name="A B")])
        save_collaborator_file(cf, path)
        raw = json.loads(path.read_text())
        assert "collaborators" in raw
        assert len(raw["collaborators"]) == 1


# ---------------------------------------------------------------------------
# resolve_person
# ---------------------------------------------------------------------------

class TestResolvePerson:

    @pytest.fixture
    def cfile(self):
        return CollaboratorFile(collaborators=[
            Collaborator(id="aaa111", name="Alice Chen"),
            Collaborator(id="bbb222", name="Bob Smith"),
        ])

    def test_exact_match(self, cfile):
        exact, suggestions = resolve_person("alice", cfile)
        assert exact is not None
        assert exact.name == "Alice Chen"
        assert suggestions == []

    def test_fuzzy_suggestions(self, cfile):
        exact, suggestions = resolve_person("alic", cfile)
        # "alic" is a prefix → exact match via matches_query
        # Actually "alic" starts "alice chen" name → matches_query returns True
        # So this is an exact match
        if exact is not None:
            assert exact.name == "Alice Chen"
        else:
            assert len(suggestions) > 0

    def test_no_match(self, cfile):
        exact, suggestions = resolve_person("zzzzzzz", cfile)
        assert exact is None
        assert suggestions == []

    def test_fuzzy_when_no_exact(self):
        cf = CollaboratorFile(collaborators=[
            Collaborator(name="Alice Chen"),
            Collaborator(name="Bob Smith"),
        ])
        # "alce" is close to "alice" but won't match prefix exactly
        exact, suggestions = resolve_person("alce", cf)
        # Should not be an exact match
        assert exact is None
        # Should get fuzzy suggestions (Alice Chen should be close)
        names = [s.name for s in suggestions]
        assert "Alice Chen" in names
