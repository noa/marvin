# Gemini & Antigravity Setup

This guide covers two Gemini integration paths — the **Gemini CLI** (terminal-based agent) and **Antigravity** (IDE-embedded agent) — and how to configure each for Marvin.

---

## Gemini CLI

### Option A: MCP Server (Recommended)

Register Marvin as a tool server. The Gemini CLI starts `marvin-mcp` as a subprocess and calls its tools via the Model Context Protocol.

```bash
# 1. Install Marvin with MCP dependencies
pip install -e ".[mcp]"

# 2. Register the server
gemini mcp add marvin -- marvin-mcp

# 3. Use it
gemini "what tasks are due this week?"
gemini "add a task to review the NSF budget by Friday"
```

### Option B: AGENTS.md (File-Level Agent)

Clone the repo and let Gemini operate directly on the data worktree using its native file tools. The `GEMINI.md` at the repo root provides agent instructions.

```bash
# 1. Clone and install
git clone <repo-url> ~/marvin && cd ~/marvin
uv pip install -e .

# 2. Initialize data
marvin setup

# 3. Run Gemini from the data directory
gemini -C ~/.marvin/data "organize my inbox"
```

In this mode, Gemini reads `GEMINI.md` for task format conventions and uses `grep`, `read_file`, `edit_file` to manipulate `tasks.json` directly. The `.gemini/settings.json` in the data directory restricts the agent to safe file operations only.

> [!IMPORTANT]
> Option B gives the agent direct file access. The CLI wrapper handles Git sync — do **not** let the agent run git commands. This is enforced by `settings.json` tool restrictions.

### Manual MCP Config

If you prefer to edit config files directly instead of using `gemini mcp add`:

**`~/.gemini/settings.json`**
```json
{
  "mcpServers": {
    "marvin": {
      "command": "marvin-mcp",
      "args": []
    }
  }
}
```

To point at a custom data directory:

```json
{
  "mcpServers": {
    "marvin": {
      "command": "marvin-mcp",
      "args": ["--data-dir", "/path/to/data"]
    }
  }
}
```

### CLI Examples

```bash
# One-liners with Gemini CLI + MCP
gemini "list my overdue tasks"
gemini "who am I waiting on?"
gemini "add a task: submit rebuttal by June 15 @waiting(Sarah)"
gemini "mark the ablation study task as done"
gemini "show me everything tagged #conference"
```

---

## Antigravity Setup

Antigravity (the IDE-embedded Gemini agent) uses **workspace rules** to understand project context. Rules are stored in `.agents/rules/` at the workspace root.

### Rule File Structure

```
.agents/
└── rules/
    ├── marvin-tasks.md       # Always-on: task management conventions
    └── marvin-budget.md      # Model-decision: budget cross-references
```

### Rule Activation Modes

| Mode | Syntax | When It Fires |
|------|--------|---------------|
| **Always On** | `alwaysApply: true` | Every agent invocation |
| **Model Decision** | (no frontmatter) | Agent decides based on relevance |
| **Glob** | `globs: ["*.json"]` | Only when matching files are in context |

### Example Rule: Task Management

**`.agents/rules/marvin-tasks.md`**
```markdown
---
alwaysApply: true
---

# Marvin Task Conventions

- Tasks are stored in `~/.marvin/data/tasks.json` (Pydantic schema)
- Use 4-character ID prefixes when referencing tasks (e.g., `ae23`)
- Tags are lowercase, no `#` prefix in JSON (e.g., `"conference"`)
- The `waiting_on` field stores a collaborator's canonical name
- Collaborators live in `~/.marvin/data/collaborators.json`
- Never modify the data directory directly — use `marvin` CLI or MCP tools
```

### Example Rule: Budget Cross-References

**`.agents/rules/marvin-budget.md`**
```markdown
# Cross-Tool: Marvin + Smaug

When a user asks about spending, budgets, or financial anomalies:
1. Query Smaug for the relevant budget data
2. If action is needed, create a Marvin task with specifics
3. Match personnel names across tools using fuzzy matching
```

---

## Combined Marvin + Smaug Config

Register both tools in a single Gemini settings file:

**`~/.gemini/settings.json`**
```json
{
  "mcpServers": {
    "marvin": {
      "command": "marvin-mcp",
      "args": []
    },
    "smaug": {
      "command": "smaug-mcp",
      "args": []
    }
  }
}
```

With both servers registered, you can issue compound requests:

```bash
gemini "check if the QUASAR grant is over budget and create a task to review it"
gemini "who on my team has unresolved budget flags? Add follow-up tasks for each."
```

The agent will call tools from both servers in a single reasoning chain, matching people by name across Marvin's collaborator records and Smaug's personnel data.
