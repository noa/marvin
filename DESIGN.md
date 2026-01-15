# CLI Commands Reference

> **Note:** The primary executable is `la` (short for lab-agent). All commands auto-sync with Git before and after execution.

## (a) Adding Tasks

```bash
# Quick capture to inbox (natural language)
la add "remind me to check Sarah's draft on Friday"
la add "review budget for NSF-2026 @deadline(2026-02-15)"
la add "email Bob about equipment list @waiting(Bob)"

# Add to a specific project
la add --project NSF-2026 "finalize co-PI agreement"
la add -p dissertation/alice "send chapter 3 feedback"

# Shorthand: omit 'add' for quick capture
la "call the grants office tomorrow"
```

## (b) Querying Tasks (Multi-Resolution)

```bash
# Today's tasks (default resolution)
la list                  # or: la ls
la list --today          # explicit: only items due today

# This week
la list --week           # tasks due within 7 days

# By project
la list --project NSF-2026
la list -p dissertation/alice

# By tag or status
la list --waiting        # all @waiting(Name) items
la list --blocked        # items you're blocked on
la list --overdue        # past-due items

# Full search (keyword or semantic)
la search "budget"       # keyword search across all projects
la search --semantic "funding deadlines"  # (if vector embeddings enabled)

# Show everything
la list --all            # all open tasks across all projects
```

## (c) Daily Briefing

```bash
# Morning briefing (default: 24h lookback, today's deadlines)
la brief                 # or: la briefing

# Custom time window
la brief --since yesterday
la brief --since "3 days ago"

# Focus on specific concerns
la brief --waiting       # who are you waiting on?
la brief --deadlines     # hard deadlines in next 7 days
la brief --students      # student-related blockers

# Output format options
la brief --format markdown   # for pasting into notes
la brief --format json       # for scripting
```

## Quick Reference Table

| Action | Command |
|--------|---------|
| Add task to inbox | `la "task description"` |
| Add to project | `la add -p PROJECT "task"` |
| Today's tasks | `la list` |
| This week | `la list --week` |
| Project status | `la list -p PROJECT` |
| Morning briefing | `la brief` |
| Who am I waiting on? | `la brief --waiting` |
| Search all tasks | `la search "keyword"` |
| Organize inbox | `la cleanup` |

---

This implementation plan outlines the development of **`lab-agent`**, a minimalist, Git-backed task assistant designed specifically for the high-context, multi-project workflow of an academic PI.

---

# Project Plan: `lab-agent`

## (a) Project Goals

* **Zero-UI Friction:** Allow task management entirely through natural language via the command line.
* **Infinite History:** Leverage Git to provide a permanent, searchable record of all research activities and completed milestones.
* **Universal Sync:** Use GitHub as a centralized "source of truth" accessible across lab workstations, home laptops, and mobile (via terminal apps).
* **Intelligence-First:** Use LLMs not just to append text, but to categorize, prioritize, and summarize complex project hierarchies.

---

## (b) User Story: The Academic PI

> "As a PI managing three active grants, four PhD students, and a heavy teaching load, I need a way to offload 'task-tracking' without opening a heavy GUI like Notion or Jira.
> When I'm in the middle of a coding session, I want to type `la "remind me to check Sarah's draft on Friday"` and know it’s synced. In the morning, I want a 30-second briefing of which student is blocking me and what grant deadlines are looming, without manually digging through folders."

---

## (c) Detailed Features

### 1. The "Transaction" Engine

* **Auto-Sync:** Every command triggers a `git pull --rebase` before execution and a `git commit && git push` after.
* **Conflict Resolution:** If a merge conflict occurs, the LLM is tasked with merging the two versions of the task list based on timestamps.

### 2. Hierarchical Project Management

* **Project Scoping:** Tasks are stored in folder-based hierarchies (e.g., `projects/NSF-2026/tasks.md`).
* **Waiting-For Tracking:** A specific metadata tag `@waiting(Name)` allows the agent to generate reports on who the PI is currently waiting on.

### 3. Smart Briefings

* **The "Morning Coffee" Report:** A summary command that analyzes the Git diffs from the last 24 hours and lists today's hard deadlines.
* **Contextual Linking:** Ability to associate tasks with local file paths (e.g., PDFs or TeX files).

### 4. Natural Language Refactoring

* **Cleanup:** A command like `la "organize my inbox"` that asks the LLM to move miscellaneous tasks into the correct project files based on content.

---

## (d) Technical Design

### 1. Architecture: Hybrid Wrapper + Coding Agent

We use a **hybrid architecture** that combines the reliability of a custom wrapper with the flexibility of a coding agent:

```
┌─────────────────────────────────────────────────────────────┐
│  User: la "remind me to check Sarah's draft on Friday"     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Thin Wrapper (la)                                          │
│  • git pull --rebase                                        │
│  • Invoke Gemini CLI with task + context                    │
│  • git add . && git commit && git push                      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Gemini CLI (coding agent)                                  │
│  • Native file search, view, and edit tools                 │
│  • Understands Markdown structure                           │
│  • Guided by AGENTS.md system prompt                        │
└─────────────────────────────────────────────────────────────┘
```

**Why Hybrid?**

| Concern | Wrapper Handles | Agent Handles |
|---------|-----------------|---------------|
| Git sync | ✅ Reliable, deterministic | ❌ Would need scripting |
| Intent parsing | ❌ Complex to implement | ✅ Native NLU |
| File editing | ❌ Must parse Markdown | ✅ Native edit tools |
| Search | ❌ Must implement | ✅ Native grep/semantic search |
| Extensibility | ❌ New code per feature | ✅ Just update prompts |

### 2. The Tech Stack

| Component | Tool/Library | Reason |
| --- | --- | --- |
| **Wrapper** | **Bash/Python script** | Minimal glue for Git sync and agent invocation. |
| **Agent Backend** | **Gemini CLI** | Provides file search, view, edit, and reasoning out of the box. |
| **Git Integration** | **Native Git CLI** | Simple, reliable; no library needed. |
| **Data Format** | **Markdown + YAML** | Human-readable files; YAML frontmatter stores metadata (deadlines, tags). |
| **Agent Config** | **GEMINI.md** | System prompt that guides agent behavior in the todo repo. |

### 3. File Schema

To keep the agent from getting lost, we use a standardized Markdown format:

```markdown
---
project: NSF-Grant-2026
status: active
priority: high
---
# Tasks
- [ ] Review budget drafts @deadline(2026-02-01)
- [ ] Email co-PI regarding equipment list @waiting(Bob)

```


### 4. Agent Logic Flow

1. **Sync:** Wrapper runs `git pull --rebase` to ensure local state is current.
2. **Delegate:** Wrapper invokes Gemini CLI with the user's natural language request:
   ```bash
   gemini -C ~/.lab-agent/data "$USER_REQUEST"
   ```
3. **Agent Execution:** Gemini CLI reads `GEMINI.md` for context, uses native tools to:
   - Search for relevant files (`grep`, `find`)
   - View file contents
   - Edit Markdown files (add tasks, update status, etc.)
4. **Commit:** Wrapper runs `git add . && git commit -m "Agent: [summary]" && git push`.
5. **Output:** Any agent output (briefings, lists) is displayed to the user.

### 5. The GEMINI.md System Prompt

The `GEMINI.md` file in the repo root guides agent behavior:

```markdown
# Todo Repository Instructions

This is a task management repository for an academic PI.

## File Structure
- `inbox.md`: Quick captures, unsorted tasks
- `projects/<name>/tasks.md`: Project-specific tasks
- `archive/`: Completed projects

## Task Format
Tasks use GitHub-style checkboxes with optional metadata:
- `- [ ] Task description @deadline(YYYY-MM-DD)`
- `- [ ] Task description @waiting(Name)`
- `- [x]` marks completed tasks

## Behavior Guidelines
1. When adding tasks without a project, use `inbox.md`
2. Preserve YAML frontmatter when editing files
3. When generating briefings, prioritize deadlines and @waiting items
4. Keep responses concise; this is a CLI tool

## Restrictions
> [!CAUTION]
> **DO NOT** interact with git in any way. The wrapper handles all git operations.
> - Never run `git` commands
> - Never modify `.git/` or `.gitignore`
> - Never attempt to commit, push, pull, or check status
> 
> If a user asks about git history or sync status, explain that the wrapper handles this automatically.
```

### 6. CLI Guardrails via `settings.json`

Soft guardrails in `GEMINI.md` can be bypassed by a creative agent. For defense-in-depth, we enforce **hard restrictions** via a local `settings.json`:

```json
{
  "tools": {
    "core": ["read_file", "write_file", "edit_file", "glob", "grep", "ls"],
    "sandbox": true
  },
  "hooks": {
    "enabled": true,
    "BeforeTool": [
      {
        "command": "reject-if-git",
        "match": "run_shell_command",
        "script": "if [[ \"$TOOL_ARGS\" == *git* ]]; then echo 'BLOCKED: git commands not allowed' >&2; exit 1; fi"
      }
    ]
  }
}
```

**Guardrail strategies:**

| Strategy | How |
|----------|-----|
| **Allowlist tools** | `tools.core` restricts to safe file operations only |
| **Sandbox execution** | `tools.sandbox: true` isolates shell commands |
| **BeforeTool hooks** | Intercept and reject any command containing `git` |


### 7. Proposed Directory Structure

```text
~/.lab-agent/
├── config.yaml          # GitHub repo URL, optional settings
├── bin/la               # The wrapper script
└── data/ (The Repo)     # Cloned GitHub repo
    ├── .gemini/
    │   └── settings.json  # CLI guardrails (tool restrictions)
    ├── GEMINI.md        # System prompt for Gemini CLI
    ├── inbox.md         # Quick captures
    ├── projects/        # One .md file per grant/paper
    └── archive/         # Completed project files
```

### 8. Example Wrapper Script

```bash
#!/bin/bash
# ~/.lab-agent/bin/la

REPO_DIR="$HOME/.lab-agent/data"
cd "$REPO_DIR" || exit 1

# Sync before
git pull --rebase --quiet

# Delegate to Gemini CLI
gemini -C "$REPO_DIR" "$*"

# Sync after
git add -A
if ! git diff --cached --quiet; then
    git commit -m "Agent: $(echo "$*" | head -c 50)"
    git push --quiet
fi
```