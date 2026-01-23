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

**DO NOT interact with git in any way.** The wrapper handles all git operations.

- Never run `git` commands
- Never modify `.git/` or `.gitignore`
- Never attempt to commit, push, pull, or check status

If a user asks about git history or sync status, explain that the wrapper handles this automatically.

## Recipes

Each recipe is a deterministic procedure. Follow steps in order. Consult `.index.yaml` first for efficiency.

### list

```yaml
recipe: list
description: List tasks with optional filters
steps:
  - action: read_file
    path: .index.yaml
    purpose: Get project summary and counts
  - action: filter_projects
    by: flags (--waiting → waiting_count > 0, --overdue → overdue_count > 0, --project → name match)
  - action: read_file
    path: "{matched_project.path}"
    for_each: matched_project
  - action: extract_lines
    pattern: "- [ ]"
    filter_by: deadline/waiting tags if specified
  - action: format_output
    style: concise CLI list grouped by project
```

### add

```yaml
recipe: add
description: Add a new task
steps:
  - action: determine_target
    if_project_specified: "projects/{project}/tasks.md"
    else: "inbox.md"
  - action: read_file
    path: "{target}"
  - action: parse_task
    extract: deadline, waiting, priority from natural language
    format: "- [ ] {description} {metadata_tags}"
  - action: append_task
    location: after last existing task (before any blank lines at end)
    preserve: YAML frontmatter
  - action: write_file
    path: "{target}"
```

### brief

```yaml
recipe: brief
description: Generate a daily briefing
steps:
  - action: read_file
    path: .index.yaml
  - action: identify_urgent
    criteria:
      - overdue_count > 0
      - next_deadline within 7 days
      - waiting_count > 0 (if --waiting flag)
  - action: read_file
    path: "{urgent_project.path}"
    for_each: urgent_project
  - action: synthesize
    include:
      - overdue items (CRITICAL)
      - items due this week
      - waiting-on summary
    format: concise bullet points
```

### cleanup

```yaml
recipe: cleanup
description: Organize inbox by moving tasks to projects
steps:
  - action: read_file
    path: inbox.md
  - action: read_file
    path: .index.yaml
  - action: for_each_task
    in: inbox.md
    steps:
      - classify: match task to existing project by keywords/context
      - if_match_found:
          - read_file: "projects/{matched}/tasks.md"
          - append_task: add to matched project file
          - remove_task: from inbox.md
      - if_no_match: leave in inbox
  - action: write_files
    modified: [inbox.md, ...matched project files]
```

### search

```yaml
recipe: search
description: Search across all tasks
steps:
  - action: read_file
    path: .index.yaml
  - action: grep_search
    pattern: "{query}"
    paths: [inbox.md, projects/**/tasks.md]
  - action: format_output
    style: list with file context
```
