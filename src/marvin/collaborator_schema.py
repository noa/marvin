"""Collaborator schema for Marvin using Pydantic.

Defines the JSON structure for collaborators.json and provides
fuzzy-match utilities for resolving names/aliases from free text.
"""

import difflib
import uuid
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field


def generate_collaborator_id() -> str:
    """Generate a short random ID for a collaborator (6 hex chars)."""
    return uuid.uuid4().hex[:6]


def _auto_aliases(name: str) -> list[str]:
    """Generate default aliases from a full name.

    'Alice Chen' → ['alice', 'chen']
    """
    parts = name.lower().split()
    # Include each word (first, last, etc.) as an alias, deduplicated
    seen: set[str] = set()
    aliases = []
    for part in parts:
        p = part.strip(".,;:")
        if p and p not in seen:
            seen.add(p)
            aliases.append(p)
    return aliases


class Collaborator(BaseModel):
    """A single collaborator / person record."""

    id: str = Field(default_factory=generate_collaborator_id)
    name: str
    role: str | None = None          # e.g. "PhD student", "collaborator"
    affiliation: str | None = None   # e.g. "MIT CSAIL"
    email: str | None = None
    aliases: list[str] = Field(default_factory=list)  # shorthand names
    notes: list[str] = Field(default_factory=list)    # free-text annotations
    tags: list[str] = Field(default_factory=list)     # searchable labels
    added_at: date = Field(default_factory=date.today)

    def all_aliases(self) -> list[str]:
        """Return the full alias list (auto-generated + user-defined), lowercased."""
        combined = set(a.lower() for a in self.aliases)
        for a in _auto_aliases(self.name):
            combined.add(a)
        return sorted(combined)

    def matches_query(self, query: str) -> bool:
        """Return True if this collaborator matches a query string exactly."""
        q = query.lower().strip()
        # Exact name match
        if self.name.lower() == q:
            return True
        # ID prefix
        if self.id.lower().startswith(q):
            return True
        # Alias exact match
        if q in self.all_aliases():
            return True
        # Name prefix (e.g. "alice" matches "Alice Chen")
        if self.name.lower().startswith(q):
            return True
        # Alias prefix (e.g. "ali" matches alias "alice")
        if any(a.startswith(q) for a in self.all_aliases()):
            return True
        return False

    def similarity_score(self, query: str) -> float:
        """Return a [0, 1] similarity score for fuzzy matching."""
        q = query.lower().strip()
        candidates = [self.name.lower()] + self.all_aliases()
        best = max(
            difflib.SequenceMatcher(None, q, c).ratio()
            for c in candidates
        )
        return best


class CollaboratorFile(BaseModel):
    """Container for all collaborator records."""

    collaborators: list[Collaborator] = Field(default_factory=list)

    def find_by_query(self, query: str) -> "Collaborator | None":
        """Find a single collaborator by exact name, alias, or ID prefix."""
        for c in self.collaborators:
            if c.matches_query(query):
                return c
        return None

    def fuzzy_matches(
        self,
        query: str,
        threshold: float = 0.6,
        limit: int = 3,
    ) -> list["Collaborator"]:
        """Return top fuzzy matches above threshold, sorted by score."""
        scored = [
            (c, c.similarity_score(query))
            for c in self.collaborators
        ]
        scored = [(c, s) for c, s in scored if s >= threshold]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [c for c, _ in scored[:limit]]


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def load_collaborator_file(path: Path) -> CollaboratorFile:
    """Load and validate collaborators.json.

    Returns an empty CollaboratorFile if the file doesn't exist.
    """
    if not path.exists():
        return CollaboratorFile()
    content = path.read_text()
    if not content.strip():
        return CollaboratorFile()
    return CollaboratorFile.model_validate_json(content)


def save_collaborator_file(cf: CollaboratorFile, path: Path) -> None:
    """Save collaborators.json."""
    path.write_text(cf.model_dump_json(indent=2))


# ---------------------------------------------------------------------------
# Fuzzy resolution helper (used by CLI)
# ---------------------------------------------------------------------------

def resolve_person(
    query: str,
    cf: CollaboratorFile,
) -> tuple["Collaborator | None", list["Collaborator"]]:
    """Resolve a person query to a collaborator.

    Returns:
        (exact_match, did_you_mean_list)
        - If an exact match is found: (collab, [])
        - If no exact match but fuzzy matches exist: (None, [collab, ...])
        - If nothing at all: (None, [])
    """
    exact = cf.find_by_query(query)
    if exact:
        return exact, []

    suggestions = cf.fuzzy_matches(query)
    return None, suggestions
