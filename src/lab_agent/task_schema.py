"""Task schema for lab-agent using Pydantic.

Defines the JSON structure for task files and provides validation.
"""

import uuid
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError


def generate_task_id() -> str:
    """Generate a short random ID for a task (6 hex chars)."""
    return uuid.uuid4().hex[:6]


class Task(BaseModel):
    """A single task item."""
    
    id: str = Field(default_factory=generate_task_id)
    description: str
    status: Literal["open", "done"] = "open"
    deadline: date | None = None
    deadline_time: str | None = None  # Specific time, e.g., "11:59 PM EST"
    waiting_on: str | None = None
    priority: Literal["high", "medium", "low"] = "medium"
    tags: list[str] = Field(default_factory=list)  # Semantic tags for filtering
    match_key: str | None = None  # Stable key for deduplication (from research)
    created_at: date = Field(default_factory=date.today)
    completed_at: date | None = None
    
    # Hierarchical relationships
    parent_id: str | None = None  # ID of parent task (if this is a subtask)
    
    def is_overdue(self) -> bool:
        """Check if task is overdue."""
        if self.status == "done" or self.deadline is None:
            return False
        return self.deadline < date.today()
    
    def is_due_within(self, days: int) -> bool:
        """Check if task is due within N days."""
        if self.status == "done" or self.deadline is None:
            return False
        delta = (self.deadline - date.today()).days
        return 0 <= delta <= days


class TaskFile(BaseModel):
    """A task file containing multiple tasks for a project."""
    
    project: str
    tasks: list[Task] = Field(default_factory=list)
    
    @property
    def open_tasks(self) -> list[Task]:
        """Get all open tasks."""
        return [t for t in self.tasks if t.status == "open"]
    
    @property
    def open_count(self) -> int:
        """Count of open tasks."""
        return len(self.open_tasks)
    
    @property
    def waiting_count(self) -> int:
        """Count of tasks waiting on someone."""
        return sum(1 for t in self.open_tasks if t.waiting_on)
    
    @property
    def overdue_count(self) -> int:
        """Count of overdue tasks."""
        return sum(1 for t in self.open_tasks if t.is_overdue())
    
    @property
    def next_deadline(self) -> date | None:
        """Get the next upcoming deadline."""
        deadlines = [
            t.deadline for t in self.open_tasks 
            if t.deadline and t.deadline >= date.today()
        ]
        return min(deadlines) if deadlines else None
    
    # Hierarchical task helpers
    
    def get_task_by_id(self, task_id: str) -> Task | None:
        """Find a task by its ID."""
        return next((t for t in self.tasks if t.id == task_id), None)
    
    def get_children(self, parent_id: str) -> list[Task]:
        """Get all direct children of a task."""
        return [t for t in self.tasks if t.parent_id == parent_id]
    
    def get_root_tasks(self) -> list[Task]:
        """Get all tasks that are not subtasks (no parent)."""
        return [t for t in self.tasks if t.parent_id is None]
    
    def get_open_root_tasks(self) -> list[Task]:
        """Get all open tasks that are not subtasks."""
        return [t for t in self.open_tasks if t.parent_id is None]
    
    def get_subtree(self, task_id: str) -> list[Task]:
        """Get a task and all its descendants (recursive)."""
        result = []
        task = self.get_task_by_id(task_id)
        if task:
            result.append(task)
            for child in self.get_children(task_id):
                result.extend(self.get_subtree(child.id))
        return result
    
    def has_open_subtasks(self, task_id: str) -> bool:
        """Check if a task has any open subtasks."""
        children = self.get_children(task_id)
        for child in children:
            if child.status == "open":
                return True
            if self.has_open_subtasks(child.id):
                return True
        return False


def load_task_file(path: Path) -> TaskFile:
    """Load and validate a task file from JSON.
    
    Args:
        path: Path to the tasks.json file
        
    Returns:
        Validated TaskFile object
        
    Raises:
        ValidationError: If JSON is invalid or doesn't match schema
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If file isn't valid JSON
    """
    content = path.read_text()
    return TaskFile.model_validate_json(content)


def save_task_file(task_file: TaskFile, path: Path) -> None:
    """Save a task file to JSON.
    
    Args:
        task_file: TaskFile to save
        path: Path to write to
    """
    path.write_text(task_file.model_dump_json(indent=2))


def validate_json_file(path: Path) -> tuple[bool, str | None]:
    """Validate a task JSON file.
    
    Args:
        path: Path to the tasks.json file
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        load_task_file(path)
        return True, None
    except ValidationError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Failed to parse JSON: {e}"


def validate_all_task_files(data_dir: Path) -> list[tuple[Path, str]]:
    """Validate the task JSON file in the data directory.
    
    Args:
        data_dir: Path to the data directory
        
    Returns:
        List of (path, error_message) tuples for invalid files.
        Empty list if all files are valid.
    """
    errors = []
    
    tasks_path = data_dir / "tasks.json"
    if tasks_path.exists():
        is_valid, error = validate_json_file(tasks_path)
        if not is_valid:
            errors.append((tasks_path, error))
    
    return errors
