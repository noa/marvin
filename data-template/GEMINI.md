# Todo Repository Instructions

This is a task management repository for an academic PI.

## File Structure

- `tasks.json`: All tasks stored in a single JSON file
- `collaborators.json`: Collaborator/people records
- `ideas.json`: Idea garden for research sparks and brainstorming

## Task Structure

Tasks are stored in JSON format with the following fields:

```json
{
  "id": "unique-uuid",
  "description": "Task description",
  "status": "open",
  "deadline": "2026-02-15",
  "deadline_time": "11:59 PM AoE",
  "waiting_on": "Person name",
  "priority": "high",
  "tags": ["conference", "deadline"],
  "parent_id": null,
  "created_at": "2026-01-15",
  "completed_at": null
}
```

### Key Fields

| Field | Purpose | Example |
|-------|---------|---------| 
| `deadline` | Hard deadline date | `"2026-02-15"` |
| `deadline_time` | Specific time (optional) | `"11:59 PM AoE"` |
| `waiting_on` | Waiting on someone | `"Bob"` |
| `priority` | Priority level | `"high"`, `"medium"`, `"low"` |
| `tags` | Categorization tags | `["conference", "deadline"]` |
| `parent_id` | Parent task ID for subtasks | `"abc123..."` |

## Collaborator Structure

Collaborators are stored in `collaborators.json`:

```json
{
  "collaborators": [
    {
      "id": "ae23f1",
      "name": "Alice Chen",
      "role": "PhD student",
      "affiliation": "MIT CSAIL",
      "email": "alice@mit.edu",
      "aliases": ["ali", "alicec"],
      "notes": ["co-author on NeurIPS 2026 paper"],
      "tags": ["student", "nlp"],
      "added_at": "2026-01-15"
    }
  ]
}
```

### Key Collaborator Fields

| Field | Purpose | Example |
|-------|---------|---------|
| `name` | Canonical display name | `"Alice Chen"` |
| `role` | Role/position | `"PhD student"`, `"collaborator"` |
| `affiliation` | Institution | `"MIT CSAIL"` |
| `email` | Email address | `"alice@mit.edu"` |
| `aliases` | Shorthand names for quick lookup | `["alice", "ali"]` |
| `notes` | Free-text annotations | `["defended proposal May 2026"]` |
| `tags` | Searchable labels | `["student", "nlp"]` |

## Idea Structure

Ideas are stored in `ideas.json` — a lightweight idea garden for capturing
research sparks, half-formed hypotheses, and potential directions before they
become actionable tasks.

### How Ideas Differ from Tasks

- **No deadline** — ideas are timeless until promoted
- **No assignee** — ideas aren't assigned to people (but can link to collaborators)
- **Decay by default** — unattended ideas automatically archive unless tended
- **Status lifecycle** — ideas progress through maturity stages, not open/done

### Idea Status Lifecycle

```
spark → developing → mature → promoted (becomes a task)
                            → archived (intentional or decay)
```

| Status | Meaning | Decay |
|--------|---------|-------|
| `spark` | Quick capture, raw thought | 30 days |
| `developing` | Being explored, has notes | 90 days |
| `mature` | Well-formed, ready to act on | No decay |
| `promoted` | Graduated to a task | Terminal |
| `archived` | Set aside (manual or decay) | Terminal |

Decay is reset whenever a note is added to an idea. The `marvin ideas tend`
command surfaces ideas approaching their decay window for triage.

### File Format

```json
{
  "ideas": [
    {
      "id": "f8a21c",
      "thought": "What if we fine-tune on code-switched data?",
      "status": "spark",
      "tags": ["ml", "multilingual"],
      "source": "conversation with Alice after EMNLP talk",
      "people": ["Alice Chen"],
      "notes": ["could leverage the WikiMatrix corpus"],
      "links": ["https://arxiv.org/abs/2025.12345"],
      "related_task_ids": [],
      "related_idea_ids": [],
      "created_at": "2026-05-01",
      "updated_at": "2026-05-01"
    }
  ]
}
```

### Key Idea Fields

| Field | Purpose | Example |
|-------|---------|---------|
| `thought` | Core idea description | `"Fine-tune on code-switched data"` |
| `status` | Maturity stage | `"spark"`, `"developing"`, `"mature"` |
| `tags` | Categorization labels | `["ml", "multilingual"]` |
| `source` | Where the idea came from | `"EMNLP 2026 keynote"` |
| `people` | Related collaborators | `["Alice Chen"]` |
| `notes` | Accumulated observations | `["could use WikiMatrix"]` |
| `links` | URLs (papers, resources) | `["https://arxiv.org/..."]` |
| `related_task_ids` | Linked tasks | `["ae23f1"]` |
| `related_idea_ids` | Linked ideas | `["b7c412"]` |

### Idea Commands

- **idea**: Capture a new spark
- **ideas**: List active ideas (with filters: `--sparks`, `--developing`)
- **ideas show**: Show full idea detail
- **ideas search**: Find ideas by keyword
- **ideas note**: Add a note (resets decay timer)
- **ideas develop**: Promote spark → developing
- **ideas mature**: Promote developing → mature
- **ideas promote**: Graduate idea to a task
- **ideas archive**: Manually archive an idea
- **ideas tend**: Triage ideas approaching decay
- **ideas tag**: Add a tag to an idea
- **ideas link**: Link to a person, task, or other idea

## Hierarchical Tasks

Tasks can be organized hierarchically using `parent_id`:
- Tasks with `parent_id: null` are root tasks
- Tasks with a `parent_id` are subtasks of the referenced task
- Subtasks can have their own subtasks for deep nesting

## Behavior Guidelines

1. **Adding tasks**: All tasks go to `tasks.json`
2. **Subtasks**: Use `parent_id` to create hierarchical grouping
3. **Briefings**: Prioritize deadlines and waiting-on items
4. **Output style**: Keep responses concise; this is a CLI tool
5. **Task completion**: Set `status` to `"done"` and `completed_at` to today's date
6. **Collaborators**: Person records go in `collaborators.json`; tasks reference them by name via `waiting_on`

## Commands Context

The user may issue these types of requests:
- **add**: Create a new task (optionally with `--parent` for subtasks)
- **list**: Show tasks with filters (today, week, tag, waiting, overdue)
- **subtasks**: Show subtasks of a specific task
- **brief**: Generate a summary of activity and upcoming items
- **search**: Find tasks by keyword or tag
- **edit**: Modify task properties (tags, deadline, priority, etc.)
- **done**: Mark a task as completed
- **rm**: Remove a task entirely
- **person add**: Add a collaborator record
- **person list**: List all collaborators
- **person show**: Show a person's profile and related tasks
- **person note**: Add a note to a collaborator
- **person edit**: Edit a collaborator's profile or aliases
- **person rm**: Remove a collaborator
- **who**: Quick collaborator lookup (alias for `person show`)
- **idea**: Capture a new idea spark
- **ideas**: List active ideas (with filters: `--sparks`, `--developing`)
- **ideas show**: Show full idea detail
- **ideas search**: Find ideas by keyword
- **ideas note**: Add a note to an idea (resets decay timer)
- **ideas develop**: Promote spark → developing
- **ideas mature**: Promote developing → mature
- **ideas promote**: Graduate an idea to a task
- **ideas archive**: Manually archive an idea
- **ideas tend**: Triage ideas approaching decay
- **ideas tag**: Add a tag to an idea
- **ideas link**: Link an idea to a person, task, or other idea

## Restrictions

**DO NOT interact with git in any way.** The wrapper handles all git operations.

- Never run `git` commands
- Never modify `.git/` or `.gitignore`
- Never attempt to commit, push, pull, or check status

If a user asks about git history or sync status, explain that the wrapper handles this automatically.

## Tag Conventions

### Conference Deadlines

For official conference deadlines, use BOTH tags:
- `conference` - indicates conference-related
- `deadline` - indicates this is an external deadline

Tasks tagged with both `#conference` and `#deadline` that have a past deadline date are automatically cleared.

### Common Tags

- `conference` - Conference-related work
- `deadline` - External deadline (use with `conference` for conference deadlines)
- `grant` - Grant-related work
- `paper` - Paper writing/research
- `teaching` - Teaching duties
- `admin` - Administrative tasks
- `student` - Student-related tasks
- `meeting` - Meeting-related tasks
