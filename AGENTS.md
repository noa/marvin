# Marvin — Agent Skill File

Marvin is a CLI tool for task management, designed for academic PIs. It tracks
tasks, deadlines, collaborators, and waiting-on blockers.

## Quick Tour: CLI vs. Agentic Usecases

Marvin operates in two modes: as a terminal CLI (`marvin` or `la`), and as an **MCP (Model Context Protocol) Server** that enables AI assistants (like Claude Desktop) to manage your research tasks, collaborator network, and research ideas.

Here is a comparison of the most useful features in both CLI and Agentic modes:

### 1. Researching Deadlines
* **CLI Mode**: Query the web or a URL to extract deadlines and automatically populate tasks.
  ```bash
  marvin research "ICML 2026 deadlines"
  ```
* **Agentic Mode**: Ask your AI assistant to browse and track deadlines.
  ```bash
  claude "check the NeurIPS 2026 website and add all the submission deadlines to my tasks"
  ```

### 2. Curating the Idea Garden
* **CLI Mode**: Capture quick research sparks. Sparks auto-decay (archive) after 30 days unless tended (by adding a note or developing them).
  ```bash
  marvin idea "contrastive pretraining might fix distribution shift" -t ml
  ```
* **Agentic Mode**: Ask your AI assistant to lookup papers, summarize, and file ideas.
  ```bash
  claude "look up the ResNet paper on arXiv and add a summary of its key findings to my notes"
  ```

### 3. Collaborators & Blocker Resolution
* **CLI Mode**: Add people, assign aliases, and link tasks using `@waiting(Name)`.
  ```bash
  marvin person add "Alice Chen" --role "PhD student" --affiliation "MIT"
  marvin add "check draft" --waiting "Alice Chen"
  ```
* **Agentic Mode**: Tell your assistant to resolve waiting-on blockers or update profiles.
  ```bash
  claude "who are we waiting on for the grant proposal? If it's Alice, add a note to her profile that we discussed it today"
  ```

### 4. Cross-Agent Reasoning (with Smaug)
* **Agentic Mode**: Combine Marvin with [Smaug](https://github.com/noa/smaug) (budget agent). Since names are shared, your assistant can cross-reference tasks with budget resources.
  ```bash
  claude "check my tasks for any upcoming travel deadlines, verify Bob's affiliation, and check if Smaug has enough travel budget allocated for him"
  ```

---

## When to use Marvin

Use Marvin when the user asks about:
- Tasks, to-dos, or action items
- Deadlines and upcoming due dates
- Daily briefings or morning summaries
- Waiting-on items (who is blocking progress?)
- Collaborator info (roles, affiliations, notes)
- Searching or filtering tasks by keyword or tag
- Research ideas and brainstorming

## Data directory

Marvin reads from a data directory at `~/.marvin`.
Override with the `MARVIN_DATA_DIR` environment variable.

The data directory contains:
```
~/.marvin/
├── GEMINI.md            # Agent guidance for task management
├── .gemini/
│   └── settings.json    # Tool restrictions (no shell access)
├── tasks.json           # All tasks (JSON, Pydantic-validated)
├── collaborators.json   # Collaborator/people records
└── ideas.json           # Idea garden (JSON, Pydantic-validated)
```

## Command reference

### Read commands (safe, no side effects)

```bash
# Task listing
marvin list                        # Today's tasks (default)
marvin list --today                # Only items due today
marvin list --week                 # Tasks due within 7 days
marvin list -t conference          # Filter by tag
marvin list --waiting              # @waiting items
marvin list --overdue              # Past-due items
marvin list --all                  # All open tasks

# Search
marvin search "budget"             # Keyword search
marvin search "#conference"        # Tag search

# Subtasks
marvin subtasks ae23               # Show subtasks of a task

# Briefing
marvin brief                       # Morning briefing
marvin brief --waiting             # Focus on who you're waiting on

# People
marvin person list                 # List all collaborators
marvin person show alice           # Show person profile + related tasks
marvin who alice                   # Quick person lookup


# Ideas
marvin ideas                       # List active ideas
marvin ideas --sparks              # Only sparks
marvin ideas --developing          # Only developing
marvin ideas show ae23             # Full idea detail
marvin ideas search "keyword"      # Search all ideas
marvin ideas tend                  # Triage expiring ideas
```

### Write commands (modify data)

```bash
# Task creation
marvin add "remind me to check Sarah's draft on Friday"
marvin add --parent ae23 "run ablation study"

# Task editing
marvin edit ae23 --add-tag conference
marvin edit ae23 --deadline 2026-02-15
marvin edit ae23 --priority high
marvin edit ae23 --waiting "Bob"

# Notes
marvin note ae23 "see shared doc"

# Completion and removal
marvin done ae23
marvin rm 72f9
marvin clear-overdue


# People management
marvin person add "Alice Chen" --role "PhD student" --affiliation "MIT"
marvin person edit alice --role postdoc
marvin person note alice "co-author on NeurIPS 2026"
marvin person rm alice

# Web research (creates tasks from found deadlines)
marvin research "ICML 2026 deadlines"
marvin research https://icml.cc/Conferences/2026

# Idea capture and management
marvin idea "thought" -t tag       # Capture a spark
marvin ideas note ae23 "text"      # Add note (resets decay)
marvin ideas develop ae23          # spark → developing
marvin ideas mature ae23           # developing → mature
marvin ideas promote ae23          # Graduate to task
marvin ideas archive ae23          # Intentional archive
marvin ideas tag ae23 ml           # Add tag
marvin ideas link ae23 --person bob  # Link to person
```

## Quick reference

| Action                  | Command                                    |
|-------------------------|--------------------------------------------|
| Add task                | `marvin add "task description"`            |
| Add subtask             | `marvin add --parent ID "subtask"`         |
| View subtasks           | `marvin subtasks ID`                       |
| Today's tasks           | `marvin list`                              |
| This week               | `marvin list --week`                       |
| Filter by tag           | `marvin list -t TAG`                       |
| Waiting-on items        | `marvin list --waiting`                    |
| Morning briefing        | `marvin brief`                             |
| Search all tasks        | `marvin search "keyword"`                  |
| Mark done               | `marvin done ID`                           |
| Edit task               | `marvin edit ID --deadline 2026-03-01`     |
| Add note                | `marvin note ID "note text"`               |
| Look up person          | `marvin who alice`                         |
| Add collaborator        | `marvin person add "Name" --role "role"`   |
| Research deadlines      | `marvin research "query"`                  |
| Capture idea            | `marvin idea "thought" -t tag`             |
| List ideas              | `marvin ideas`                             |
| Show idea               | `marvin ideas show ID`                     |
| Develop idea            | `marvin ideas develop ID`                  |
| Promote idea to task    | `marvin ideas promote ID`                  |
| Tend idea garden        | `marvin ideas tend`                        |
| Clear past-due items    | `marvin clear-overdue`                     |

## Important conventions

- **Task IDs** are 6-hex-char UUIDs; use the first 4 characters as shorthand
  (e.g., `ae23` instead of `ae23f1`)
- **Collaborator names** support fuzzy matching and aliases — `alice`, `Alice`,
  or `Alice Chen` all resolve to the same person
- **Waiting-on** uses `@waiting(Name)` to track who is blocking a task; names
  are auto-linked to known collaborators
- **Tags** like `#conference` + `#deadline` auto-clear when the deadline passes
- **Ideas auto-decay** — sparks archive after 30 days, developing ideas after
  90 days, unless tended (adding a note resets the timer)
- **`marvin ideas tend`** surfaces ideas approaching their decay window for
  garden triage — review, add a note, develop, or let them archive
- **Ideas can be promoted** to tasks via `marvin ideas promote`, which creates
  a new task from the idea and marks the idea as promoted
- **`marvin` vs `la`** — the CLI is installed as `marvin` but also aliased
  as `la` (lab-agent). Both work identically

## MCP Server

Marvin ships an MCP server for agent tool integration:

```bash
pip install -e ".[mcp]"
marvin-mcp  # Starts MCP server on stdio
```

Register in your MCP client configuration:
```json
{
  "mcpServers": {
    "marvin": { "command": "marvin-mcp" }
  }
}
```

## Cross-tool integration with Smaug

Marvin can be used alongside [Smaug](https://github.com/noa/smaug) (academic
budget tracking). Register both MCP servers to enable agents to reason across
tasks and budgets:

```json
{
  "mcpServers": {
    "marvin": { "command": "marvin-mcp" },
    "smaug":  { "command": "smaug-mcp" }
  }
}
```

This enables cross-tool reasoning — for example:
- Checking if a grant deadline task is tied to a project approaching stop-work
- Verifying that a new hire mentioned in a task has budget allocated
- Correlating travel tasks with travel budget line items

There is no code-level coupling between Marvin and Smaug. Integration happens
through agent reasoning: personnel names use fuzzy matching across both tools,
so `"Alice Chen"` in a Marvin task will match the same person in Smaug's
personnel records.
