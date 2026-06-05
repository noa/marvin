# Marvin Codebase Conventions

This rule provides structural context and constraints for modifying the Marvin codebase.

## Application Scope
- **Activation Mode**: Model Decision or Glob-based
- **Glob Pattern**: `src/**/*.py`, `tests/**/*.py`, `data-template/**`

## Code Style & Formatting
- **Python Version**: Target Python 3.11+. Use modern type hints and syntax where possible.
- **Formatter**: Code must adhere to Ruff rules (100-character line limit, double quotes for strings, 4-space indentation).
- **Type Checking**: Write explicit types for all public interfaces.
- **CLI Framework**: All CLI commands use Click. Follow established patterns in `cli.py` — use `@click.command()`, `@click.option()`, and `@click.argument()` decorators.
- **Data Validation**: Use Pydantic models for all structured data (tasks, collaborators). Define schemas explicitly and validate on load/save.

## Marvin Conventions & Safety
- **Naming Standards**:
  - Task IDs are 6-hex-character UUIDs (e.g., `a3f9c1`). Use the first 4 characters as shorthand for display and user-facing references (e.g., `a3f9`).
  - Collaborator names support fuzzy matching via aliases. Always use alias-aware lookup when resolving collaborator references.
- **Data Storage**: All persistent data is stored as JSON files (`tasks.json`, `collaborators.json`) inside the data directory (`~/.marvin/data`, configurable via `LA_DATA_DIR`).
- **Data Template**: The `data-template/` directory is the canonical template deployed to `~/.marvin/data` on first run. Changes here affect new installations.
- **Git Safety**: Git operations (pull, commit, push) are managed exclusively by the CLI wrapper (`cli.py`). **NEVER** run git commands in agent code or Gemini instructions. Do not modify `.git/` or `.gitignore` under any circumstances.
- **Write Operations**: All data modifications go through the JSON files in the data directory. Do not write to any files outside the data directory during normal task operations.
