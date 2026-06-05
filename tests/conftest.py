"""Shared pytest fixtures for marvin schema tests."""

import json

import pytest


@pytest.fixture
def data_dir(tmp_path):
    """Create a temp directory with empty tasks.json, collaborators.json, and ideas.json."""
    tasks_path = tmp_path / "tasks.json"
    tasks_path.write_text(json.dumps({"project": "default", "tasks": []}))

    collabs_path = tmp_path / "collaborators.json"
    collabs_path.write_text(json.dumps({"collaborators": []}))

    ideas_path = tmp_path / "ideas.json"
    ideas_path.write_text(json.dumps({"ideas": []}))

    return tmp_path


@pytest.fixture
def sample_task():
    """Return a representative task dict."""
    return {
        "description": "Finish literature review",
        "deadline": "2026-07-01",
        "waiting_on": "Dr. Smith",
        "priority": "high",
        "tags": ["writing", "review"],
    }


@pytest.fixture
def sample_collaborator():
    """Return a representative collaborator dict."""
    return {
        "name": "Alice Chen",
        "role": "PhD student",
        "affiliation": "MIT CSAIL",
        "email": "alice@mit.edu",
    }


@pytest.fixture
def sample_idea():
    """Return a representative idea dict."""
    return {
        "thought": "Contrastive pretraining might fix distribution shift",
        "tags": ["ml", "transfer-learning"],
        "source": "reading: Chen et al. 2026",
    }
