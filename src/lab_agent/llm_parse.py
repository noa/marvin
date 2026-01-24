"""LLM parsing for natural language task input.

Uses Gemini CLI to parse natural language into structured task JSON,
then Python handles the file writing.
"""

import json
import re
import subprocess
from datetime import date
from pathlib import Path

from lab_agent.task_schema import Task, TaskFile, load_task_file, save_task_file


# Prompt template for parsing natural language to task JSON
PARSE_PROMPT = '''Parse this task into JSON format. Output ONLY valid JSON, no other text.

Task: {task_text}
Today's date: {today}

Output format:
{{
  "description": "cleaned task description without metadata tags",
  "deadline": "YYYY-MM-DD or null",
  "waiting_on": "person name or null",
  "priority": "high, medium, or low",
  "tags": ["tag1", "tag2"]
}}

Tag rules:
1. Extract explicit tags: #conference → "conference", #grant → "grant"
2. Infer 1-3 semantic tags from context (e.g., "email Bob" → ["communication"])
3. Common tag categories: conference, grant, paper, teaching, admin, student, meeting, review, deadline

Examples:
- "call Bob about grant @deadline(2026-02-15)" → {{"description": "call Bob about grant", "deadline": "2026-02-15", "waiting_on": null, "priority": "medium", "tags": ["communication", "grant"]}}
- "submit ICML paper #conference" → {{"description": "submit ICML paper", "deadline": null, "waiting_on": null, "priority": "medium", "tags": ["conference", "paper"]}}
- "grade homework for CS101" → {{"description": "grade homework for CS101", "deadline": null, "waiting_on": null, "priority": "medium", "tags": ["teaching", "grading"]}}

Output JSON only:'''


def parse_task_with_llm(task_text: str, data_dir: Path) -> dict | None:
    """Use Gemini CLI to parse natural language task into structured data.
    
    Args:
        task_text: Natural language task description
        data_dir: Data directory (for context)
        
    Returns:
        Parsed task dict or None if parsing failed
    """
    today = date.today().isoformat()
    prompt = PARSE_PROMPT.format(task_text=task_text, today=today)
    
    try:
        result = subprocess.run(
            ["gemini", prompt],
            cwd=data_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        output = result.stdout.strip()
        
        # Try to extract JSON from the output
        # Handle case where LLM includes extra text
        json_match = re.search(r'\{[^{}]*\}', output, re.DOTALL)
        if json_match:
            output = json_match.group(0)
        
        parsed = json.loads(output)
        return parsed
        
    except subprocess.TimeoutExpired:
        return None
    except json.JSONDecodeError:
        return None
    except Exception:
        return None


def parse_task_locally(task_text: str) -> dict:
    """Parse task using simple regex patterns (fallback).
    
    Args:
        task_text: Natural language task description
        
    Returns:
        Parsed task dict
    """
    description = task_text
    deadline = None
    waiting_on = None
    priority = "medium"
    tags = []
    
    # Extract @deadline(YYYY-MM-DD)
    deadline_match = re.search(r'@deadline\((\d{4}-\d{2}-\d{2})\)', task_text)
    if deadline_match:
        deadline = deadline_match.group(1)
        description = description.replace(deadline_match.group(0), '').strip()
    
    # Extract @waiting(Name)
    waiting_match = re.search(r'@waiting\(([^)]+)\)', task_text)
    if waiting_match:
        waiting_on = waiting_match.group(1)
        description = description.replace(waiting_match.group(0), '').strip()
    
    # Extract @priority(level)
    priority_match = re.search(r'@priority\((high|medium|low)\)', task_text)
    if priority_match:
        priority = priority_match.group(1)
        description = description.replace(priority_match.group(0), '').strip()
    
    # Extract #hashtag style tags
    tag_matches = re.findall(r'#(\w+)', description)
    if tag_matches:
        tags = [t.lower() for t in tag_matches]
        # Remove tags from description
        description = re.sub(r'#\w+', '', description).strip()
    
    # Clean up extra whitespace
    description = ' '.join(description.split())
    
    return {
        "description": description,
        "deadline": deadline,
        "waiting_on": waiting_on,
        "priority": priority,
        "tags": tags,
    }


def add_task(
    data_dir: Path,
    task_text: str,
    project: str | None = None,
    use_llm: bool = True,
) -> Task:
    """Add a task to inbox or project.
    
    Args:
        data_dir: Path to data directory
        task_text: Natural language task description
        project: Optional project name
        use_llm: Whether to use LLM for parsing (falls back to regex)
        
    Returns:
        The created Task object
    """
    # Determine target file
    if project:
        target_path = data_dir / "projects" / project / "tasks.json"
        if not target_path.exists():
            # Create new project
            target_path.parent.mkdir(parents=True, exist_ok=True)
            task_file = TaskFile(project=project, tasks=[])
        else:
            task_file = load_task_file(target_path)
    else:
        target_path = data_dir / "inbox.json"
        if not target_path.exists():
            task_file = TaskFile(project="inbox", tasks=[])
        else:
            task_file = load_task_file(target_path)
    
    # Parse the task
    parsed = None
    if use_llm:
        parsed = parse_task_with_llm(task_text, data_dir)
    
    if parsed is None:
        # Fallback to local parsing
        parsed = parse_task_locally(task_text)
    
    # Create the task
    task = Task(
        description=parsed["description"],
        deadline=parsed.get("deadline"),
        waiting_on=parsed.get("waiting_on"),
        priority=parsed.get("priority", "medium"),
        tags=parsed.get("tags", []),
    )
    
    # Add to task file and save
    task_file.tasks.append(task)
    save_task_file(task_file, target_path)
    
    return task


# Prompt template for research (web search + task creation)
RESEARCH_PROMPT = '''Search the web for: {query}

Today's date is {today}. The user's timezone is {timezone}.

Based on your search results, extract any relevant deadlines, dates, or action items.
Output a JSON array of tasks. Each task should have:
- match_key: a stable identifier to match this deadline if we search again (e.g., "icml-2026-abstract", "neurips-2026-paper")
- description: what needs to be done
- deadline: date in YYYY-MM-DD format (or null if no specific date)
- deadline_time: specific time in the user's timezone if available, e.g., "11:59 PM EST" or "23:59 UTC-5" (or null if not specified)
- priority: "high" for imminent deadlines (within 2 weeks), "medium" otherwise
- tags: 1-3 semantic tags (e.g., ["conference", "paper"])

IMPORTANT: Look for specific deadline TIMES, not just dates. Conference deadlines often have specific times like "11:59 PM AoE" or "23:59 UTC".

Output ONLY a valid JSON array, no other text. Example format:
[
  {{"match_key": "icml-2026-abstract", "description": "ICML 2026 abstract submission", "deadline": "2026-01-30", "deadline_time": "11:59 PM AoE", "priority": "high", "tags": ["conference", "deadline"]}},
  {{"match_key": "icml-2026-paper", "description": "ICML 2026 full paper deadline", "deadline": "2026-02-06", "deadline_time": "11:59 PM AoE", "priority": "high", "tags": ["conference", "paper"]}}
]

If no relevant deadlines found, output: []

JSON array:'''


def get_user_timezone() -> str:
    """Get the user's current timezone as a string like 'EST' or 'UTC-5'."""
    import time
    # Get timezone offset in hours
    if time.daylight and time.localtime().tm_isdst:
        offset_seconds = -time.altzone
        tz_name = time.tzname[1]
    else:
        offset_seconds = -time.timezone
        tz_name = time.tzname[0]
    
    offset_hours = offset_seconds // 3600
    offset_sign = "+" if offset_hours >= 0 else ""
    
    # Return common name if available, otherwise UTC offset
    if tz_name and tz_name not in ("", "UTC"):
        return f"{tz_name} (UTC{offset_sign}{offset_hours})"
    return f"UTC{offset_sign}{offset_hours}"


def research_and_add_tasks(
    data_dir: Path,
    query: str,
    project: str | None = None,
) -> tuple[list[Task], list[Task]]:
    """Research a topic via web search and create/update tasks from findings.
    
    Uses match_key for deduplication - if a task with the same match_key
    already exists, it will be updated rather than duplicated.
    
    Args:
        data_dir: Path to data directory
        query: Search query (e.g., "ICML 2026 deadlines")
        project: Optional project to add tasks to
        
    Returns:
        Tuple of (created_tasks, updated_tasks)
    """
    today = date.today().isoformat()
    timezone = get_user_timezone()
    prompt = RESEARCH_PROMPT.format(query=query, today=today, timezone=timezone)
    
    try:
        # Run Gemini with a longer timeout for web search
        result = subprocess.run(
            ["gemini", prompt],
            cwd=data_dir,
            capture_output=True,
            text=True,
            timeout=60,  # Longer timeout for web search
        )
        
        output = result.stdout.strip()
        
        # Try to extract JSON array from the output
        # Handle case where LLM includes extra text
        json_match = re.search(r'\[.*\]', output, re.DOTALL)
        if json_match:
            output = json_match.group(0)
        
        parsed_tasks = json.loads(output)
        
        if not isinstance(parsed_tasks, list):
            return [], []
        
    except subprocess.TimeoutExpired:
        raise RuntimeError("Search timed out. Please try again.")
    except json.JSONDecodeError:
        raise RuntimeError("Could not parse search results. Please try a different query.")
    except Exception as e:
        raise RuntimeError(f"Search failed: {e}")
    
    if not parsed_tasks:
        return [], []
    
    # Determine target file
    if project:
        target_path = data_dir / "projects" / project / "tasks.json"
        if not target_path.exists():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            task_file = TaskFile(project=project, tasks=[])
        else:
            task_file = load_task_file(target_path)
    else:
        target_path = data_dir / "inbox.json"
        if not target_path.exists():
            task_file = TaskFile(project="inbox", tasks=[])
        else:
            task_file = load_task_file(target_path)
    
    # Build index of existing tasks by match_key for quick lookup
    existing_by_key: dict[str, Task] = {}
    for task in task_file.tasks:
        if task.match_key:
            existing_by_key[task.match_key] = task
    
    # Create/update tasks from parsed results
    created_tasks = []
    updated_tasks = []
    
    for item in parsed_tasks:
        if not isinstance(item, dict) or "description" not in item:
            continue
        
        match_key = item.get("match_key")
        
        # Check if we should update an existing task
        if match_key and match_key in existing_by_key:
            existing_task = existing_by_key[match_key]
            
            # Update fields (newer info overwrites if present)
            if item.get("deadline"):
                # Parse deadline string to date object
                try:
                    existing_task.deadline = date.fromisoformat(item["deadline"])
                except ValueError:
                    pass  # Keep existing deadline if parsing fails
            if item.get("deadline_time"):
                existing_task.deadline_time = item["deadline_time"]
            if item.get("priority"):
                existing_task.priority = item["priority"]
            if item.get("tags"):
                # Merge tags
                existing_tags = set(existing_task.tags)
                existing_tags.update(item["tags"])
                existing_task.tags = sorted(existing_tags)
            if item.get("description"):
                existing_task.description = item["description"]
            
            updated_tasks.append(existing_task)
        else:
            # Create new task
            task = Task(
                description=item["description"],
                deadline=item.get("deadline"),
                deadline_time=item.get("deadline_time"),
                waiting_on=item.get("waiting_on"),
                priority=item.get("priority", "medium"),
                tags=item.get("tags", []),
                match_key=match_key,
            )
            task_file.tasks.append(task)
            created_tasks.append(task)
    
    # Save if anything changed
    if created_tasks or updated_tasks:
        save_task_file(task_file, target_path)
    
    return created_tasks, updated_tasks

