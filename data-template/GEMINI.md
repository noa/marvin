# Todo Repository Instructions

This is a task management repository for an academic PI.

## File Structure

- `tasks.json`: All tasks stored in a single JSON file

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
