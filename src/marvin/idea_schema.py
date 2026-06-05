"""Idea schema for Marvin using Pydantic.

Defines the JSON structure for idea files. Ideas are research thoughts
that decay by default — they auto-archive unless deliberately tended.
"""

import uuid
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


# Decay windows (days) by status
SPARK_DECAY_DAYS = 30
DEVELOPING_DECAY_DAYS = 90

# Warning windows (days before archive)
SPARK_WARNING_DAYS = 7
DEVELOPING_WARNING_DAYS = 14


def generate_idea_id() -> str:
    """Generate a short random ID for an idea (6 hex chars)."""
    return uuid.uuid4().hex[:6]


class IdeaNote(BaseModel):
    """A timestamped note on an idea."""

    text: str
    added_at: date = Field(default_factory=date.today)


IdeaStatus = Literal["spark", "developing", "mature", "promoted", "archived"]


class Idea(BaseModel):
    """A single research idea."""

    id: str = Field(default_factory=generate_idea_id)
    thought: str
    status: IdeaStatus = "spark"
    tags: list[str] = Field(default_factory=list)
    source: str | None = None
    people: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    notes: list[IdeaNote] = Field(default_factory=list)
    related_task_ids: list[str] = Field(default_factory=list)
    related_idea_ids: list[str] = Field(default_factory=list)
    promoted_to: str | None = None
    created_at: date = Field(default_factory=date.today)
    last_tended_at: date | None = None
    archived_at: date | None = None
    archive_reason: str | None = None  # "auto-decay", "manual", "promoted"

    def _decay_anchor(self) -> date:
        """The date from which the decay clock starts."""
        return self.last_tended_at or self.created_at

    def _max_days(self) -> int | None:
        """Maximum days before auto-archive, or None if no decay."""
        if self.status == "spark":
            return SPARK_DECAY_DAYS
        elif self.status == "developing":
            return DEVELOPING_DECAY_DAYS
        return None

    def _warning_days(self) -> int | None:
        """Warning window in days, or None if no decay."""
        if self.status == "spark":
            return SPARK_WARNING_DAYS
        elif self.status == "developing":
            return DEVELOPING_WARNING_DAYS
        return None

    def days_until_archive(self) -> int | None:
        """Days until auto-archive, or None if no decay applies."""
        max_days = self._max_days()
        if max_days is None:
            return None
        elapsed = (date.today() - self._decay_anchor()).days
        return max(0, max_days - elapsed)

    def is_warning(self) -> bool:
        """True if idea is in its warning window (approaching auto-archive)."""
        remaining = self.days_until_archive()
        if remaining is None:
            return False
        threshold = self._warning_days()
        if threshold is None:
            return False
        return remaining <= threshold

    def is_expired(self) -> bool:
        """True if the decay clock has run out."""
        remaining = self.days_until_archive()
        if remaining is None:
            return False
        return remaining == 0

    def tend(self, note_text: str) -> None:
        """Add a note and reset the decay clock."""
        self.notes.append(IdeaNote(text=note_text))
        self.last_tended_at = date.today()


class IdeaFile(BaseModel):
    """Container for all ideas."""

    ideas: list[Idea] = Field(default_factory=list)

    @property
    def active_ideas(self) -> list[Idea]:
        """All non-archived, non-promoted ideas."""
        return [i for i in self.ideas if i.status not in ("archived", "promoted")]

    @property
    def sparks(self) -> list[Idea]:
        """Ideas with spark status."""
        return [i for i in self.ideas if i.status == "spark"]

    @property
    def developing_ideas(self) -> list[Idea]:
        """Ideas with developing status."""
        return [i for i in self.ideas if i.status == "developing"]

    @property
    def mature_ideas(self) -> list[Idea]:
        """Ideas with mature status."""
        return [i for i in self.ideas if i.status == "mature"]

    def find_by_id(self, id_prefix: str) -> Idea | None:
        """Find an idea by ID prefix match."""
        id_prefix = id_prefix.lower()
        for idea in self.ideas:
            if idea.id.lower().startswith(id_prefix):
                return idea
        return None

    def expiring_ideas(self, within_days: int | None = None) -> list[Idea]:
        """Ideas in their warning window, sorted by urgency.

        Args:
            within_days: If set, only ideas expiring within this many days.
                         If None, uses the status-specific warning window.
        """
        result = []
        for idea in self.active_ideas:
            if within_days is not None:
                remaining = idea.days_until_archive()
                if remaining is not None and remaining <= within_days:
                    result.append(idea)
            elif idea.is_warning():
                result.append(idea)

        # Sort by urgency (fewest days remaining first)
        result.sort(key=lambda i: i.days_until_archive() or 999)
        return result

    def expired_ideas(self) -> list[Idea]:
        """Ideas past their decay deadline."""
        return [i for i in self.active_ideas if i.is_expired()]


def load_idea_file(path: Path) -> IdeaFile:
    """Load and validate an idea file from JSON.

    Returns empty IdeaFile if file doesn't exist or is empty.
    """
    if not path.exists():
        return IdeaFile()
    content = path.read_text()
    if not content.strip():
        return IdeaFile()
    return IdeaFile.model_validate_json(content)


def save_idea_file(idea_file: IdeaFile, path: Path) -> None:
    """Save an idea file to JSON."""
    path.write_text(idea_file.model_dump_json(indent=2))
