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

Today's date is {today}.

Based on your search results, extract any relevant deadlines, dates, or action items.
Output a JSON array of tasks. Each task should have:
- description: what needs to be done
- deadline: date in YYYY-MM-DD format (or null if no specific date)
- priority: "high" for imminent deadlines (within 2 weeks), "medium" otherwise
- tags: 1-3 semantic tags (e.g., ["conference", "paper"])

Output ONLY a valid JSON array, no other text. Example format:
[
  {{"description": "ICML 2026 abstract submission", "deadline": "2026-01-30", "priority": "high", "tags": ["conference", "deadline"]}},
  {{"description": "ICML 2026 full paper deadline", "deadline": "2026-02-06", "priority": "high", "tags": ["conference", "paper"]}}
]

If no relevant deadlines found, output: []

JSON array:'''


def research_and_add_tasks(
    data_dir: Path,
    query: str,
    project: str | None = None,
) -> list[Task]:
    """Research a topic via web search and create tasks from findings.
    
    Args:
        data_dir: Path to data directory
        query: Search query (e.g., "ICML 2026 deadlines")
        project: Optional project to add tasks to
        
    Returns:
        List of created Task objects
    """
    today = date.today().isoformat()
    prompt = RESEARCH_PROMPT.format(query=query, today=today)
    
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
            return []
        
    except subprocess.TimeoutExpired:
        raise RuntimeError("Search timed out. Please try again.")
    except json.JSONDecodeError:
        raise RuntimeError("Could not parse search results. Please try a different query.")
    except Exception as e:
        raise RuntimeError(f"Search failed: {e}")
    
    if not parsed_tasks:
        return []
    
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
    
    # Create tasks from parsed results
    created_tasks = []
    for item in parsed_tasks:
        if not isinstance(item, dict) or "description" not in item:
            continue
            
        task = Task(
            description=item["description"],
            deadline=item.get("deadline"),
            waiting_on=item.get("waiting_on"),
            priority=item.get("priority", "medium"),
            tags=item.get("tags", []),
        )
        task_file.tasks.append(task)
        created_tasks.append(task)
    
    # Save all tasks
    if created_tasks:
        save_task_file(task_file, target_path)
    
    return created_tasks
