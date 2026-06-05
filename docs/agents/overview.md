# Agentic Integration Overview

Marvin exposes its task management capabilities through three channels, each suited to a different agent architecture. This guide helps you pick the right one and get running quickly.

## Integration Channels

### 1. MCP Server (`marvin-mcp`)

The **Model Context Protocol** server is the primary integration point for AI agents. It runs as a subprocess (stdio transport) and exposes structured JSON tools that any MCP-compatible host can call.

```bash
# Start the server (agents do this automatically via config)
marvin-mcp
marvin-mcp --data-dir /path/to/data
```

**Best for:** Claude Desktop, Gemini CLI, any MCP-compatible agent framework.

### 2. CLI Commands (`marvin`)

The CLI is a thin Python wrapper around Git sync + Gemini CLI. Each command pulls before execution and commits/pushes after. Agents can shell out to `marvin` directly when MCP isn't available.

```bash
marvin add "review Sarah's draft by Friday"
marvin list --week
marvin brief --waiting
```

**Best for:** Shell-based agents, Siri Shortcuts, scripts, cron jobs.

### 3. Python Internals (`fast_path` module)

The `fast_path` module provides deterministic, LLM-free Python functions for reading and writing tasks. Import it directly when you need programmatic access without subprocess overhead.

```python
from marvin import fast_path

tf = fast_path.load_tasks(data_dir)
for task in tf.open_tasks:
    if task.is_overdue():
        print(task.description)
```

**Best for:** Custom Python agents, test harnesses, embedding Marvin in larger systems.

---

## Execution Contexts

Marvin supports two deployment modes depending on whether you have a local clone of the source repo.

### Cloned Repo (Developer)

You have the Marvin source checked out and installed in editable mode. The Gemini CLI can read `GEMINI.md` and `.gemini/settings.json` from the repo root for full agent-guided behavior.

```bash
git clone <repo-url> ~/marvin && cd ~/marvin
uv pip install -e ".[mcp]"
marvin setup
```

- Full CLI + MCP + Python access
- Gemini CLI can operate as a coding agent inside the data worktree
- You can modify agent prompts in `data-template/GEMINI.md`

### Standalone MCP (End-User)

Install Marvin and register `marvin-mcp` with your agent host. No source checkout required once installed.

```bash
pip install -e ".[mcp]"       # or from PyPI when published
gemini mcp add marvin -- marvin-mcp
```

- MCP tools only — no direct file access
- Agent host manages the server lifecycle
- Data directory auto-initializes at `~/.marvin/data`

---

## Choosing the Right Channel

| Agent Architecture | Recommended Channel | Notes |
|----|----|----|
| Claude Desktop | MCP Server | Add to `claude_desktop_config.json` |
| Gemini CLI | MCP Server or AGENTS.md | MCP for tool calls; AGENTS.md for file-level agent |
| Custom Python agent | `fast_path` module | Direct import, no subprocess |
| Shell scripts / cron | CLI (`marvin`) | One-liner commands with auto-sync |
| Apple Shortcuts / Siri | CLI via SSH | `marvin add "..."` over SSH |
| Multi-tool agent (Marvin + Smaug) | MCP Server | Co-register both servers |

---

## Cross-Tool Setup: Marvin + Smaug

Marvin (task management) and [Smaug](https://github.com/your-org/smaug) (budget tracking) are designed to work together under the same agent host. There is no code-level coupling — the agent reasons across both tool sets and uses fuzzy name matching to correlate people across systems.

### Co-Registration

Register both MCP servers with your agent host:

```bash
# Gemini CLI
gemini mcp add marvin -- marvin-mcp
gemini mcp add smaug  -- smaug-mcp

# Or in ~/.gemini/settings.json
```

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

### How Cross-Tool Reasoning Works

When both servers are registered, the agent can:

1. **Query Smaug** for budget anomalies or spending reports
2. **Create Marvin tasks** referencing specific findings
3. **Match personnel** — Marvin's collaborator aliases fuzzy-match against Smaug's personnel records
4. **Chain actions** — e.g., "check if the QUASAR grant is over budget, and if so, create a task to review it"

> [!NOTE]
> Cross-tool workflows rely entirely on the agent's reasoning. Neither server calls the other directly.

---

## Quick Diagnostics

Verify your installation and data state:

```bash
# Check CLI is installed and see available commands
marvin --help

# List all open tasks (confirms data dir + git sync work)
marvin list --all

# Check MCP server is installed
marvin-mcp --help
```

If `marvin list --all` shows tasks, your setup is working. If it triggers first-time setup, follow the prompts to initialize the data directory.
