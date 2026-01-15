# Todo Repository Instructions

This is a task management repository for an academic PI.

## File Structure

- `inbox.md`: Quick captures, unsorted tasks
- `projects/<name>/tasks.md`: Project-specific tasks
- `archive/`: Completed projects

## Task Format

Tasks use GitHub-style checkboxes with optional metadata:

```markdown
- [ ] Task description @deadline(YYYY-MM-DD)
- [ ] Task description @waiting(Name)
- [x] Completed task
```

### Metadata Tags

| Tag | Purpose | Example |
|-----|---------|---------|
| `@deadline(DATE)` | Hard deadline | `@deadline(2026-02-15)` |
| `@waiting(NAME)` | Waiting on someone | `@waiting(Bob)` |
| `@priority(high\|medium\|low)` | Priority level | `@priority(high)` |

## Behavior Guidelines

1. **Adding tasks**: If no project is specified, add to `inbox.md`
2. **YAML frontmatter**: Preserve frontmatter when editing files
3. **Briefings**: Prioritize deadlines and @waiting items
4. **Output style**: Keep responses concise; this is a CLI tool
5. **Task completion**: Mark with `[x]` and optionally add completion date

## File Frontmatter

Each task file should have YAML frontmatter:

```yaml
---
project: Project Name
status: active | completed | on-hold
priority: high | medium | low
---
```

## Commands Context

The user may issue these types of requests:
- **add**: Create a new task
- **list**: Show tasks with filters (today, week, project, waiting, overdue)
- **brief**: Generate a summary of activity and upcoming items
- **search**: Find tasks by keyword or semantically
- **cleanup**: Organize inbox by moving tasks to appropriate projects

## Restrictions

> [!CAUTION]
> **DO NOT** interact with git in any way. The wrapper handles all git operations.
> - Never run `git` commands
> - Never modify `.git/` or `.gitignore`
> - Never attempt to commit, push, pull, or check status
>
> If a user asks about git history or sync status, explain that the wrapper handles this automatically.

