# lab-agent

Git-backed CLI task assistant for academic PIs, powered by Gemini CLI.

## Installation

```bash
# Clone and install
git clone <your-repo-url> lab-agent
cd lab-agent
uv venv && source .venv/bin/activate
uv pip install -e .
```

## Setup

Run the setup command to initialize your data directory:

```bash
la setup
```

This automatically:
- Creates an orphan `data` branch for your tasks
- Sets up a git worktree at `~/.lab-agent/data`
- Copies template files (inbox, project structure, agent config)
- Pushes to remote if available

> **Note:** Setup runs automatically on first use of any command, so you can skip this and just start using `la`.

## Usage

```bash
la "remind me to check Sarah's draft"   # Quick capture
la add -p NSF-2026 "finalize budget"    # Add to project
la list                                  # Today's tasks
la list --week                           # This week
la brief                                 # Daily briefing
la search "budget"                       # Search tasks
la cleanup                               # Organize inbox
```

## Configuration

Set `LA_DATA_DIR` to override the default data location:

```bash
export LA_DATA_DIR=/path/to/your/data
```

---

<details>
<summary><strong>Troubleshooting: Git Worktree</strong></summary>

### Don't delete the main repo

The worktree at `~/.lab-agent/data` depends on the main repo. If you delete or move the main repo, the worktree will break.

**Fix:** Re-clone the repo and run `la setup --force`.

### Worktree path is absolute

If you move your home directory or user, the worktree path breaks.

**Fix:** Run `la setup --force` to recreate the worktree.

### Cloning on a new machine

After cloning on a new machine, just run `la setup` — it will fetch the existing `data` branch from remote and set up the worktree.

### Pushing the data branch

When in `~/.lab-agent/data`, you're on the `data` branch. Push goes to `origin/data`, not `origin/main`. The CLI handles this automatically, but if you manually edit files:

```bash
cd ~/.lab-agent/data
git push  # Pushes to origin/data
```

</details>