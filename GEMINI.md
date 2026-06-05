# Marvin CLI

A Git-backed task assistant for academic PIs.

## Project Structure

```
src/marvin/
├── cli.py          # Main CLI entry point (Click-based)
└── __init__.py

data-template/      # Template deployed to ~/.marvin/data
├── GEMINI.md       # Agent guidance for task management
├── .gemini/
│   └── settings.json  # Tool restrictions (no shell access)
├── inbox.md
└── projects/
```

## Development

```bash
# Install in development mode
uv pip install -e .

# Run CLI
.venv/bin/marvin --help
```

## Architecture

The CLI uses a **hybrid wrapper + coding agent** pattern:

1. **Wrapper** (`cli.py`): Handles git sync (pull before, commit/push after)
2. **Agent** (Gemini CLI): Handles NLU and file editing, invoked via `gemini -C`

See [DESIGN.md](file:///Users/nandrews/todo/DESIGN.md) for full details.

## Key Files

| File | Purpose |
|------|---------|
| `cli.py` | All CLI commands (add, note, list, brief, search, cleanup, undo, reset) |
| `data-template/GEMINI.md` | Agent instructions for task management |
| `data-template/.gemini/settings.json` | Tool restrictions (allowlist, no shell) |
