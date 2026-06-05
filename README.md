# Marvin

> "Brain the size of a planet and here I am managing your to-do list."

Git-backed CLI task assistant for academic PIs, powered by Gemini CLI.

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

## Installation

```bash
# Clone and install
git clone <your-repo-url> marvin
cd marvin
uv venv && source .venv/bin/activate
uv pip install -e .
```

## Setup

Run the setup command to initialize your data directory:

```bash
marvin setup
```

This automatically:
- Creates an orphan `data` branch for your tasks
- Sets up a git worktree at `~/.marvin/data`
- Copies template files (tasks.json, agent config)
- Pushes to remote if available

> **Note:** Setup runs automatically on first use of any command, so you can skip this and just start using `marvin`.

## Usage

```bash
marvin "remind me to check Sarah's draft"   # Quick capture
marvin add --parent ae23 "run ablation"     # Add subtask
marvin note ae23 "see shared Overleaf doc"  # Annotate a task
marvin list                                  # Today's tasks
marvin list --week                           # This week
marvin list -t conference                    # Filter by tag
marvin subtasks ae23                         # View subtasks
marvin brief                                 # Daily briefing
marvin search "budget"                       # Search tasks
```

## Configuration

Set `LA_DATA_DIR` to override the default data location:

```bash
export LA_DATA_DIR=/path/to/your/data
```

---

## Mobile Access (Voice Capture)

Add tasks from your phone using **Siri + Apple Shortcuts**.

### Prerequisites
- A server with `marvin` installed (e.g., work server, VPS)
- SSH access from your phone to that server
- Git credentials configured on the server for push

### Setup

#### 1. Server Setup (one-time)

SSH into your server and run:

```bash
# Clone the repo (fetches both main and data branches)
git clone git@github.com:YOUR_USER/marvin.git ~/marvin
cd ~/marvin

# Install marvin
python -m venv .venv && source .venv/bin/activate
pip install -e .

# Run setup to create worktree at ~/.marvin/data
marvin setup

# Verify it works
marvin list
```

> **Note:** The server needs Git push access. If using SSH keys, ensure `~/.ssh/id_ed25519` (or similar) is configured and the public key is added to your GitHub account.

#### 2. iPhone Shortcut
   
   | Step | Action | Configuration |
   |------|--------|---------------|
   | 1 | **Dictate Text** | (captures your voice) |
   | 2 | **Run Script Over SSH** | Host: `your-server.edu`<br>User: `username`<br>Auth: SSH Key<br>Script: `marvin add "[Dictated Text]"` |
   | 3 | **Show Notification** | "Task added!" |

3. **Add Siri phrase:** Open Shortcut settings → "Add to Siri" → say "Add todo".

### Usage

> "Hey Siri, add todo" → *"Check Sarah's draft on Friday"* → ✅ Task synced

---

<details>
<summary><strong>Troubleshooting: Git Worktree</strong></summary>

### Don't delete the main repo

The worktree at `~/.marvin/data` depends on the main repo. If you delete or move the main repo, the worktree will break.

**Fix:** Re-clone the repo and run `marvin setup --force`.

### Worktree path is absolute

If you move your home directory or user, the worktree path breaks.

**Fix:** Run `marvin setup --force` to recreate the worktree.

### Cloning on a new machine

After cloning on a new machine, just run `marvin setup` — it will fetch the existing `data` branch from remote and set up the worktree.

### Pushing the data branch

When in `~/.marvin/data`, you're on the `data` branch. Push goes to `origin/data`, not `origin/main`. The CLI handles this automatically, but if you manually edit files:

```bash
cd ~/.marvin/data
git push  # Pushes to origin/data
```

</details>