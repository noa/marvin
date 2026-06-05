# Getting Started with MCP Agents

Marvin includes native support for the **Model Context Protocol (MCP)**, an open standard that enables AI agents to interact with task management data through schema-validated tools.

> [!NOTE]
> **Who is the MCP setup for?**
> * **Recommended for End-Users:** If you simply want to manage tasks, track deadlines, and look up collaborators without modifying Marvin's code, configure the `marvin-mcp` server. **You do not need to clone the repository.**
> * **For Developers:** If you plan to customize Marvin or use coding agents to modify the codebase, clone the repo and run your agent from the repository root instead.

---

## 1. Installation

Since Marvin is not published to PyPI, install from a cloned repository:

```bash
pip install -e ".[mcp]"
# or using uv:
uv pip install -e ".[mcp]"
```

Verify the MCP server executable:

```bash
marvin-mcp --help
```

---

## 2. Configuration for MCP Clients

### Claude Desktop (macOS)

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "marvin": {
      "command": "marvin-mcp"
    }
  }
}
```

> [!TIP]
> Marvin reads from `~/.marvin/data` by default. To use a custom directory:
> ```json
> {
>   "mcpServers": {
>     "marvin": {
>       "command": "marvin-mcp",
>       "env": {
>         "LA_DATA_DIR": "/absolute/path/to/custom/data"
>       }
>     }
>   }
> }
> ```

Restart Claude Desktop. A plug icon confirms the tools are loaded.

### Gemini CLI

```bash
gemini mcp add marvin -- marvin-mcp
```

Verify with the `/mcp` command inside the Gemini CLI.

### Multi-Server Configuration (Marvin + Smaug)

Register both Marvin and Smaug for cross-domain reasoning:

```json
{
  "mcpServers": {
    "marvin": { "command": "marvin-mcp" },
    "smaug":  { "command": "smaug-mcp" }
  }
}
```

This enables agents to reason across tasks and budgets — e.g., checking if a grant deadline task is for a project approaching stop-work.

---

## 3. Tool Reference

| Tool | CLI Equivalent | Description |
|:---|:---|:---|
| `list_tasks` | `marvin list` | List tasks with filters (today, week, tag, waiting, overdue) |
| `get_brief` | `marvin brief` | Daily briefing with overdue items and waiting-on summary |
| `search_tasks` | `marvin search` | Keyword or tag search across all tasks |
| `show_subtasks` | `marvin subtasks` | List subtasks of a given task |
| `add_task` | `marvin add` | Create a new task from natural language |
| `edit_task` | `marvin edit` | Modify task properties (tags, deadline, priority, etc.) |
| `add_note_to_task` | `marvin note` | Add a note to a task |
| `mark_task_done` | `marvin done` | Mark a task as completed |
| `remove_task` | `marvin rm` | Permanently remove a task |
| `clear_overdue_tasks` | `marvin clear-overdue` | Mark all overdue tasks as done |
| `list_people` | `marvin person list` | List all collaborators |
| `show_person` | `marvin person show` | Show collaborator profile and related tasks |
| `add_person` | `marvin person add` | Add a new collaborator |
| `add_note_to_person` | `marvin person note` | Add a note to a collaborator |
| `remove_person` | `marvin person rm` | Remove a collaborator record |

---

## 4. Best Practices

- **Query first**: Start by listing tasks to retrieve correct task IDs before making edits.
- **Multi-step reasoning**: MCP tools allow the agent to list tasks, inspect details, make changes, and verify results iteratively.
- **Context efficiency**: Tools return only requested data, preserving your model's context window.
- **Cross-tool workflows**: When used alongside Smaug, let the agent query both tools to combine task urgency with budget health.
