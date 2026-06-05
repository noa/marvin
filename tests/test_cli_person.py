"""Tests for collaborator-related CLI commands in marvin.cli.

Covers: person add, person list, person show, person note,
        person edit, person rm, and the `who` alias.
"""

import json

import pytest
from click.testing import CliRunner

from marvin.cli import main


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    """Set up a minimal data dir with seed files and patch away setup."""
    (tmp_path / "tasks.json").write_text('{"project": "default", "tasks": []}')
    (tmp_path / "collaborators.json").write_text('{"collaborators": []}')

    monkeypatch.setattr("marvin.cli.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("marvin.cli.is_setup_complete", lambda: True)

    return tmp_path



@pytest.fixture
def runner():
    return CliRunner()


def _read_collabs(tmp_path):
    """Convenience: load collaborators.json as a dict."""
    return json.loads((tmp_path / "collaborators.json").read_text())


def _add_alice(runner, extra_args=None):
    """Helper to add the canonical 'Alice Chen' collaborator."""
    args = [
        "person", "add", "Alice Chen",
        "--role", "PhD student",
        "--affiliation", "MIT",
        "--email", "alice@mit.edu",
        "--alias", "ali",
        "--tag", "student",
    ]
    if extra_args:
        args.extend(extra_args)
    return runner.invoke(main, args)


def _add_bob(runner):
    """Helper to add a second collaborator 'Bob Smith'."""
    return runner.invoke(main, [
        "person", "add", "Bob Smith",
        "--role", "postdoc",
        "--affiliation", "Stanford",
        "--email", "bob@stanford.edu",
    ])


# ===================================================================
# 1. person add
# ===================================================================

class TestPersonAdd:
    """Tests for `marvin person add`."""

    def test_add_basic(self, runner, cli_env):
        result = _add_alice(runner)
        assert result.exit_code == 0, result.output
        assert "Added collaborator" in result.output
        assert "Alice Chen" in result.output

    def test_add_fields_in_output(self, runner, cli_env):
        result = _add_alice(runner)
        assert result.exit_code == 0
        assert "PhD student" in result.output
        assert "MIT" in result.output
        assert "alice@mit.edu" in result.output
        # alias should appear
        assert "ali" in result.output

    def test_add_writes_json(self, runner, cli_env):
        _add_alice(runner)
        data = _read_collabs(cli_env)
        assert len(data["collaborators"]) == 1
        c = data["collaborators"][0]
        assert c["name"] == "Alice Chen"
        assert c["role"] == "PhD student"
        assert c["affiliation"] == "MIT"
        assert c["email"] == "alice@mit.edu"
        assert "ali" in c["aliases"]
        assert "student" in c["tags"]

    def test_add_generates_id(self, runner, cli_env):
        _add_alice(runner)
        data = _read_collabs(cli_env)
        c = data["collaborators"][0]
        assert "id" in c
        assert len(c["id"]) == 6  # 6 hex chars

    def test_add_duplicate_name_fails(self, runner, cli_env):
        r1 = _add_alice(runner)
        assert r1.exit_code == 0
        r2 = _add_alice(runner)
        assert r2.exit_code != 0
        assert "already exists" in r2.output

    def test_add_duplicate_case_insensitive(self, runner, cli_env):
        """Duplicate detection is case-insensitive."""
        _add_alice(runner)
        r = runner.invoke(main, ["person", "add", "alice chen"])
        assert r.exit_code != 0

    def test_add_minimal(self, runner, cli_env):
        """Adding with only a name (no options) should succeed."""
        r = runner.invoke(main, ["person", "add", "Jane Doe"])
        assert r.exit_code == 0
        assert "Added collaborator" in r.output
        data = _read_collabs(cli_env)
        c = data["collaborators"][0]
        assert c["name"] == "Jane Doe"
        assert c["role"] is None
        assert c["aliases"] == []

    def test_add_multiple_aliases(self, runner, cli_env):
        r = runner.invoke(main, [
            "person", "add", "Alice Chen",
            "--alias", "ali",
            "--alias", "ac",
        ])
        assert r.exit_code == 0
        data = _read_collabs(cli_env)
        c = data["collaborators"][0]
        assert "ali" in c["aliases"]
        assert "ac" in c["aliases"]

    def test_add_multiple_tags(self, runner, cli_env):
        r = runner.invoke(main, [
            "person", "add", "Alice Chen",
            "--tag", "student",
            "--tag", "#advisor",
        ])
        assert r.exit_code == 0
        data = _read_collabs(cli_env)
        c = data["collaborators"][0]
        # Tags should be lowercased and stripped of '#'
        assert "student" in c["tags"]
        assert "advisor" in c["tags"]

    def test_add_unicode_name(self, runner, cli_env):
        r = runner.invoke(main, ["person", "add", "José García"])
        assert r.exit_code == 0
        data = _read_collabs(cli_env)
        assert data["collaborators"][0]["name"] == "José García"

    def test_add_two_different_people(self, runner, cli_env):
        _add_alice(runner)
        _add_bob(runner)
        data = _read_collabs(cli_env)
        assert len(data["collaborators"]) == 2
        names = {c["name"] for c in data["collaborators"]}
        assert names == {"Alice Chen", "Bob Smith"}


# ===================================================================
# 2. person list
# ===================================================================

class TestPersonList:
    """Tests for `marvin person list`."""

    def test_list_empty(self, runner, cli_env):
        r = runner.invoke(main, ["person", "list"])
        assert r.exit_code == 0
        assert "No collaborators" in r.output

    def test_list_shows_names(self, runner, cli_env):
        _add_alice(runner)
        _add_bob(runner)
        r = runner.invoke(main, ["person", "list"])
        assert r.exit_code == 0
        assert "Alice Chen" in r.output
        assert "Bob Smith" in r.output

    def test_list_shows_count(self, runner, cli_env):
        _add_alice(runner)
        _add_bob(runner)
        r = runner.invoke(main, ["person", "list"])
        # Should show "(2)" somewhere in the output
        assert "(2)" in r.output


# ===================================================================
# 3. person show
# ===================================================================

class TestPersonShow:
    """Tests for `marvin person show`."""

    def test_show_by_first_name(self, runner, cli_env):
        _add_alice(runner)
        r = runner.invoke(main, ["person", "show", "alice"])
        assert r.exit_code == 0
        assert "Alice Chen" in r.output

    def test_show_by_alias(self, runner, cli_env):
        _add_alice(runner)
        r = runner.invoke(main, ["person", "show", "ali"])
        assert r.exit_code == 0
        assert "Alice Chen" in r.output

    def test_show_by_full_name(self, runner, cli_env):
        _add_alice(runner)
        r = runner.invoke(main, ["person", "show", "Alice Chen"])
        assert r.exit_code == 0
        assert "Alice Chen" in r.output

    def test_show_by_id_prefix(self, runner, cli_env):
        _add_alice(runner)
        data = _read_collabs(cli_env)
        cid = data["collaborators"][0]["id"]
        r = runner.invoke(main, ["person", "show", cid[:4]])
        assert r.exit_code == 0
        assert "Alice Chen" in r.output

    def test_show_not_found(self, runner, cli_env):
        r = runner.invoke(main, ["person", "show", "nobody"])
        assert r.exit_code != 0
        assert "not found" in r.output

    def test_show_fuzzy_did_you_mean(self, runner, cli_env):
        _add_alice(runner)
        r = runner.invoke(main, ["person", "show", "alicee"])
        assert r.exit_code != 0
        assert "Did you mean" in r.output

    def test_show_not_found_no_collabs(self, runner, cli_env):
        """When no collaborators exist at all, just 'not found'."""
        r = runner.invoke(main, ["person", "show", "ghost"])
        assert r.exit_code != 0
        assert "not found" in r.output


# ===================================================================
# 4. person note
# ===================================================================

class TestPersonNote:
    """Tests for `marvin person note`."""

    def test_note_success(self, runner, cli_env):
        _add_alice(runner)
        r = runner.invoke(main, ["person", "note", "alice", "co-author on NeurIPS 2026"])
        assert r.exit_code == 0
        assert "Note added" in r.output

    def test_note_persisted(self, runner, cli_env):
        _add_alice(runner)
        runner.invoke(main, ["person", "note", "alice", "first note"])
        runner.invoke(main, ["person", "note", "alice", "second note"])
        data = _read_collabs(cli_env)
        notes = data["collaborators"][0]["notes"]
        assert "first note" in notes
        assert "second note" in notes

    def test_note_not_found(self, runner, cli_env):
        r = runner.invoke(main, ["person", "note", "nobody", "some text"])
        assert r.exit_code != 0
        assert "not found" in r.output

    def test_note_fuzzy_suggest(self, runner, cli_env):
        _add_alice(runner)
        r = runner.invoke(main, ["person", "note", "alicee", "note text"])
        assert r.exit_code != 0
        assert "Did you mean" in r.output

    def test_note_by_alias(self, runner, cli_env):
        _add_alice(runner)
        r = runner.invoke(main, ["person", "note", "ali", "note via alias"])
        assert r.exit_code == 0
        data = _read_collabs(cli_env)
        assert "note via alias" in data["collaborators"][0]["notes"]


# ===================================================================
# 5. person edit
# ===================================================================

class TestPersonEdit:
    """Tests for `marvin person edit`."""

    def test_edit_role(self, runner, cli_env):
        _add_alice(runner)
        r = runner.invoke(main, ["person", "edit", "alice", "--role", "postdoc"])
        assert r.exit_code == 0
        assert "Updated" in r.output
        data = _read_collabs(cli_env)
        assert data["collaborators"][0]["role"] == "postdoc"

    def test_edit_add_alias(self, runner, cli_env):
        _add_alice(runner)
        r = runner.invoke(main, ["person", "edit", "alice", "--alias", "alicec"])
        assert r.exit_code == 0
        data = _read_collabs(cli_env)
        assert "alicec" in data["collaborators"][0]["aliases"]

    def test_edit_multiple_fields(self, runner, cli_env):
        _add_alice(runner)
        r = runner.invoke(main, [
            "person", "edit", "alice",
            "--role", "postdoc",
            "--alias", "alicec",
            "--affiliation", "Stanford",
        ])
        assert r.exit_code == 0
        data = _read_collabs(cli_env)
        c = data["collaborators"][0]
        assert c["role"] == "postdoc"
        assert c["affiliation"] == "Stanford"
        assert "alicec" in c["aliases"]

    def test_edit_clear_role(self, runner, cli_env):
        """Passing an empty string clears the field."""
        _add_alice(runner)
        r = runner.invoke(main, ["person", "edit", "alice", "--role", ""])
        assert r.exit_code == 0
        data = _read_collabs(cli_env)
        assert data["collaborators"][0]["role"] is None

    def test_edit_not_found(self, runner, cli_env):
        r = runner.invoke(main, ["person", "edit", "nobody", "--role", "prof"])
        assert r.exit_code != 0
        assert "not found" in r.output

    def test_edit_remove_alias(self, runner, cli_env):
        _add_alice(runner)
        # Add extra alias first
        runner.invoke(main, ["person", "edit", "alice", "--alias", "alicec"])
        # Then remove it
        r = runner.invoke(main, ["person", "edit", "alice", "--remove-alias", "alicec"])
        assert r.exit_code == 0
        data = _read_collabs(cli_env)
        assert "alicec" not in data["collaborators"][0]["aliases"]

    def test_edit_add_tag(self, runner, cli_env):
        _add_alice(runner)
        r = runner.invoke(main, ["person", "edit", "alice", "--tag", "coauthor"])
        assert r.exit_code == 0
        data = _read_collabs(cli_env)
        assert "coauthor" in data["collaborators"][0]["tags"]

    def test_edit_remove_tag(self, runner, cli_env):
        _add_alice(runner)
        r = runner.invoke(main, ["person", "edit", "alice", "--remove-tag", "student"])
        assert r.exit_code == 0
        data = _read_collabs(cli_env)
        assert "student" not in data["collaborators"][0]["tags"]

    def test_edit_name(self, runner, cli_env):
        _add_alice(runner)
        r = runner.invoke(main, ["person", "edit", "alice", "--name", "Alice C. Chen"])
        assert r.exit_code == 0
        data = _read_collabs(cli_env)
        assert data["collaborators"][0]["name"] == "Alice C. Chen"

    def test_edit_email(self, runner, cli_env):
        _add_alice(runner)
        r = runner.invoke(main, ["person", "edit", "alice", "--email", "new@mit.edu"])
        assert r.exit_code == 0
        data = _read_collabs(cli_env)
        assert data["collaborators"][0]["email"] == "new@mit.edu"


# ===================================================================
# 6. person rm
# ===================================================================

class TestPersonRm:
    """Tests for `marvin person rm`."""

    def test_rm_with_force(self, runner, cli_env):
        _add_alice(runner)
        r = runner.invoke(main, ["person", "rm", "alice", "--force"])
        assert r.exit_code == 0
        assert "Removed" in r.output
        data = _read_collabs(cli_env)
        assert len(data["collaborators"]) == 0

    def test_rm_not_found(self, runner, cli_env):
        r = runner.invoke(main, ["person", "rm", "nobody", "--force"])
        assert r.exit_code != 0
        assert "not found" in r.output

    def test_rm_confirm_yes(self, runner, cli_env):
        """Without --force, a confirmation prompt appears; answer 'y'."""
        _add_alice(runner)
        r = runner.invoke(main, ["person", "rm", "alice"], input="y\n")
        assert r.exit_code == 0
        assert "Removed" in r.output
        data = _read_collabs(cli_env)
        assert len(data["collaborators"]) == 0

    def test_rm_confirm_no(self, runner, cli_env):
        """Declining the confirmation keeps the collaborator."""
        _add_alice(runner)
        r = runner.invoke(main, ["person", "rm", "alice"], input="n\n")
        assert r.exit_code != 0  # Aborted
        data = _read_collabs(cli_env)
        assert len(data["collaborators"]) == 1

    def test_rm_by_id_prefix(self, runner, cli_env):
        _add_alice(runner)
        data = _read_collabs(cli_env)
        cid = data["collaborators"][0]["id"]
        r = runner.invoke(main, ["person", "rm", cid[:4], "--force"])
        assert r.exit_code == 0
        data = _read_collabs(cli_env)
        assert len(data["collaborators"]) == 0

    def test_rm_does_not_remove_other(self, runner, cli_env):
        """Removing Alice should leave Bob intact."""
        _add_alice(runner)
        _add_bob(runner)
        r = runner.invoke(main, ["person", "rm", "alice", "--force"])
        assert r.exit_code == 0
        data = _read_collabs(cli_env)
        assert len(data["collaborators"]) == 1
        assert data["collaborators"][0]["name"] == "Bob Smith"

    def test_rm_fuzzy_suggest(self, runner, cli_env):
        _add_alice(runner)
        r = runner.invoke(main, ["person", "rm", "alicee", "--force"])
        assert r.exit_code != 0
        assert "Did you mean" in r.output


# ===================================================================
# 7. who (alias for person show)
# ===================================================================

class TestWho:
    """Tests for `marvin who`."""

    def test_who_found(self, runner, cli_env):
        _add_alice(runner)
        r = runner.invoke(main, ["who", "alice"])
        assert r.exit_code == 0
        assert "Alice Chen" in r.output

    def test_who_by_alias(self, runner, cli_env):
        _add_alice(runner)
        r = runner.invoke(main, ["who", "ali"])
        assert r.exit_code == 0
        assert "Alice Chen" in r.output

    def test_who_not_found_suggests_add(self, runner, cli_env):
        r = runner.invoke(main, ["who", "nobody"])
        assert r.exit_code != 0
        assert "not found" in r.output
        assert "marvin person add" in r.output

    def test_who_fuzzy(self, runner, cli_env):
        _add_alice(runner)
        r = runner.invoke(main, ["who", "alicee"])
        assert r.exit_code != 0
        assert "Did you mean" in r.output

    def test_who_by_full_name(self, runner, cli_env):
        _add_alice(runner)
        r = runner.invoke(main, ["who", "Alice Chen"])
        assert r.exit_code == 0
        assert "Alice Chen" in r.output

    def test_who_by_id_prefix(self, runner, cli_env):
        _add_alice(runner)
        data = _read_collabs(cli_env)
        cid = data["collaborators"][0]["id"]
        r = runner.invoke(main, ["who", cid[:4]])
        assert r.exit_code == 0
        assert "Alice Chen" in r.output


# ===================================================================
# Edge cases / integration
# ===================================================================

class TestEdgeCases:
    """Cross-cutting edge cases."""

    def test_add_then_show_then_rm(self, runner, cli_env):
        """Full lifecycle: add → show → rm."""
        _add_alice(runner)
        r = runner.invoke(main, ["person", "show", "alice"])
        assert r.exit_code == 0
        r = runner.invoke(main, ["person", "rm", "alice", "--force"])
        assert r.exit_code == 0
        r = runner.invoke(main, ["person", "show", "alice"])
        assert r.exit_code != 0

    def test_note_then_show(self, runner, cli_env):
        """Notes should be visible through 'person show'."""
        _add_alice(runner)
        runner.invoke(main, ["person", "note", "alice", "defended thesis"])
        r = runner.invoke(main, ["person", "show", "alice"])
        assert r.exit_code == 0
        # The note text should appear in the person card
        assert "defended thesis" in r.output

    def test_edit_then_lookup_by_new_alias(self, runner, cli_env):
        """After adding an alias via edit, we can look up by it."""
        _add_alice(runner)
        runner.invoke(main, ["person", "edit", "alice", "--alias", "drchen"])
        r = runner.invoke(main, ["person", "show", "drchen"])
        assert r.exit_code == 0
        assert "Alice Chen" in r.output

    def test_empty_collaborators_file(self, runner, cli_env):
        """Gracefully handles an empty collaborators.json."""
        (cli_env / "collaborators.json").write_text("")
        r = runner.invoke(main, ["person", "list"])
        assert r.exit_code == 0
        assert "No collaborators" in r.output

    def test_missing_collaborators_file(self, runner, cli_env):
        """Gracefully handles a missing collaborators.json."""
        (cli_env / "collaborators.json").unlink()
        r = runner.invoke(main, ["person", "list"])
        assert r.exit_code == 0
        assert "No collaborators" in r.output

    def test_person_add_creates_file_if_missing(self, runner, cli_env):
        """Adding a person when collaborators.json doesn't exist yet."""
        (cli_env / "collaborators.json").unlink()
        r = _add_alice(runner)
        assert r.exit_code == 0
        assert (cli_env / "collaborators.json").exists()

    def test_who_shows_related_tasks(self, runner, cli_env):
        """Tasks with waiting_on matching the person should show up."""
        _add_alice(runner)
        # Write a task that is waiting on Alice
        tasks = {
            "project": "default",
            "tasks": [
                {
                    "id": "aabbcc",
                    "description": "Review draft",
                    "status": "open",
                    "tags": [],
                    "notes": [],
                    "waiting_on": "Alice Chen",
                }
            ],
        }
        (cli_env / "tasks.json").write_text(json.dumps(tasks))
        r = runner.invoke(main, ["who", "alice"])
        assert r.exit_code == 0
        assert "Review draft" in r.output
