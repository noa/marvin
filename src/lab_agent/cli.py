"""Lab Agent CLI - A thin wrapper around Gemini CLI with Git sync."""

import subprocess
import sys
import shutil
import threading
import time
from pathlib import Path

import click

from lab_agent.index_schema import rebuild_index

# Default data directory: worktree checked out to ~/.lab-agent/data
DEFAULT_DATA_DIR = Path.home() / ".lab-agent" / "data"

# Template directory (relative to installed package)
TEMPLATE_DIR = Path(__file__).parent.parent.parent / "data-template"


def get_data_dir() -> Path:
    """Get the data directory path."""
    # Check environment variable first, then fall back to default
    import os
    data_dir = os.environ.get("LA_DATA_DIR")
    if data_dir:
        return Path(data_dir)
    return DEFAULT_DATA_DIR


def is_setup_complete() -> bool:
    """Check if the data directory is set up and is a valid git worktree."""
    data_dir = get_data_dir()
    if not data_dir.exists():
        return False
    # Check if it's a valid git directory
    git_dir = data_dir / ".git"
    if not git_dir.exists():
        return False
    return True


def find_main_repo() -> Path | None:
    """Find the main lab-agent repository (where the CLI was installed from)."""
    # Try common locations
    candidates = [
        TEMPLATE_DIR.parent,  # Adjacent to installed package
        Path.home() / "lab-agent",
        Path.home() / "code" / "lab-agent",
        Path.home() / "projects" / "lab-agent",
    ]
    
    for candidate in candidates:
        if (candidate / ".git").exists() and (candidate / "data-template").exists():
            return candidate
    
    return None


def run_setup(skip_prompts: bool = False) -> bool:
    """Run the data directory setup. Returns True if successful."""
    data_dir = get_data_dir()
    main_repo = find_main_repo()
    
    if not main_repo:
        click.echo("Error: Could not find the main lab-agent repository.", err=True)
        click.echo("Please run this command from the lab-agent repo directory,", err=True)
        click.echo("or set LA_REPO_DIR to point to it.", err=True)
        return False
    
    template_dir = main_repo / "data-template"
    if not template_dir.exists():
        click.echo(f"Error: Template directory not found at {template_dir}", err=True)
        return False
    
    click.echo(f"Setting up lab-agent data directory at {data_dir}...")
    click.echo(f"Using main repo at {main_repo}")
    
    try:
        # Step 1: Check if data branch exists
        result = subprocess.run(
            ["git", "branch", "--list", "data"],
            cwd=main_repo,
            capture_output=True,
            text=True,
        )
        data_branch_exists = bool(result.stdout.strip())
        
        # Also check remote
        if not data_branch_exists:
            result = subprocess.run(
                ["git", "ls-remote", "--heads", "origin", "data"],
                cwd=main_repo,
                capture_output=True,
                text=True,
            )
            if result.stdout.strip():
                # Fetch the remote branch
                click.echo("Fetching data branch from remote...")
                subprocess.run(
                    ["git", "fetch", "origin", "data:data"],
                    cwd=main_repo,
                    check=True,
                    capture_output=True,
                )
                data_branch_exists = True
        
        # Step 2: Create orphan data branch if needed
        if not data_branch_exists:
            click.echo("Creating data branch...")
            current_branch = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=main_repo,
                capture_output=True,
                text=True,
            ).stdout.strip() or "main"
            
            subprocess.run(
                ["git", "checkout", "--orphan", "data"],
                cwd=main_repo,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "rm", "-rf", "."],
                cwd=main_repo,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "commit", "--allow-empty", "-m", "Initialize data branch"],
                cwd=main_repo,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "checkout", current_branch],
                cwd=main_repo,
                check=True,
                capture_output=True,
            )
        
        # Step 3: Create worktree directory
        data_dir.parent.mkdir(parents=True, exist_ok=True)
        
        # Remove existing worktree if present but broken
        if data_dir.exists():
            click.echo("Removing existing data directory...")
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(data_dir)],
                cwd=main_repo,
                capture_output=True,
            )
            if data_dir.exists():
                shutil.rmtree(data_dir)
        
        # Step 4: Add worktree
        click.echo("Creating worktree...")
        subprocess.run(
            ["git", "worktree", "add", str(data_dir), "data"],
            cwd=main_repo,
            check=True,
            capture_output=True,
        )
        
        # Step 5: Copy template files if the data dir is empty (new branch)
        existing_files = list(data_dir.glob("*"))
        # Filter out .git
        existing_files = [f for f in existing_files if f.name != ".git"]
        
        if not existing_files:
            click.echo("Copying template files...")
            for item in template_dir.iterdir():
                dest = data_dir / item.name
                if item.is_dir():
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)
            
            # Commit the initial files
            subprocess.run(
                ["git", "add", "-A"],
                cwd=data_dir,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "Initial data files"],
                cwd=data_dir,
                check=True,
                capture_output=True,
            )
        
        # Step 6: Push to remote (if remote exists)
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=data_dir,
            capture_output=True,
        )
        if result.returncode == 0:
            click.echo("Pushing to remote...")
            subprocess.run(
                ["git", "push", "-u", "origin", "data"],
                cwd=data_dir,
                capture_output=True,
            )
        
        click.echo("✓ Setup complete!")
        click.echo(f"  Data directory: {data_dir}")
        return True
        
    except subprocess.CalledProcessError as e:
        click.echo(f"Error during setup: {e}", err=True)
        if e.stderr:
            click.echo(e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr, err=True)
        return False


def ensure_setup() -> bool:
    """Ensure setup is complete, running it if needed. Returns True if ready."""
    if is_setup_complete():
        return True
    
    click.echo("Lab Agent data directory not found. Running first-time setup...\n")
    return run_setup()


def git_sync_before(data_dir: Path) -> bool:
    """Pull latest changes from remote. Returns True if successful."""
    try:
        subprocess.run(
            ["git", "pull", "--rebase", "--quiet"],
            cwd=data_dir,
            check=True,
            capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        click.echo("Warning: git pull failed, continuing with local state", err=True)
        return False


def git_sync_after(data_dir: Path, message: str) -> bool:
    """Commit and push any changes. Returns True if changes were pushed."""
    try:
        # Rebuild index before staging
        try:
            rebuild_index(data_dir)
        except Exception as e:
            click.echo(f"Warning: index rebuild failed: {e}", err=True)
        
        # Stage all changes
        subprocess.run(
            ["git", "add", "-A"],
            cwd=data_dir,
            check=True,
            capture_output=True,
        )
        
        # Check if there are changes to commit
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=data_dir,
            capture_output=True,
        )
        
        if result.returncode != 0:  # There are changes
            # Show diff summary
            diff_result = subprocess.run(
                ["git", "diff", "--cached", "--stat"],
                cwd=data_dir,
                capture_output=True,
                text=True,
            )
            if diff_result.stdout.strip():
                click.echo("\n" + diff_result.stdout.strip())
            
            # Commit
            subprocess.run(
                ["git", "commit", "-m", f"Agent: {message[:50]}"],
                cwd=data_dir,
                check=True,
                capture_output=True,
            )
            # Push
            subprocess.run(
                ["git", "push", "--quiet"],
                cwd=data_dir,
                check=True,
                capture_output=True,
            )
            return True
        return False
    except subprocess.CalledProcessError as e:
        click.echo(f"Warning: git sync failed: {e}", err=True)
        return False


def invoke_gemini(data_dir: Path, prompt: str) -> int:
    """Invoke Gemini CLI with the given prompt. Returns exit code."""
    stop_spinner = threading.Event()
    
    def spinner():
        """Display a spinning indicator while waiting."""
        chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        i = 0
        while not stop_spinner.is_set():
            sys.stderr.write(f"\r{chars[i % len(chars)]} Thinking...")
            sys.stderr.flush()
            i += 1
            time.sleep(0.1)
        # Clear the spinner line
        sys.stderr.write("\r" + " " * 20 + "\r")
        sys.stderr.flush()
    
    try:
        # Start spinner in background
        spinner_thread = threading.Thread(target=spinner, daemon=True)
        spinner_thread.start()
        
        result = subprocess.run(
            ["gemini", prompt],
            cwd=data_dir,
        )
        
        # Stop spinner
        stop_spinner.set()
        spinner_thread.join(timeout=0.5)
        
        return result.returncode
    except FileNotFoundError:
        stop_spinner.set()
        click.echo("Error: 'gemini' CLI not found. Please install the Gemini CLI.", err=True)
        return 1


@click.group(invoke_without_command=True)
@click.argument("task", nargs=-1)
@click.pass_context
def main(ctx: click.Context, task: tuple[str, ...]) -> None:
    """Lab Agent - Git-backed task assistant.
    
    Quick capture: la "remind me to check Sarah's draft"
    
    First time? Run: la setup
    """
    if ctx.invoked_subcommand is None:
        if task:
            # Shorthand: treat as add command
            ctx.invoke(add, task=" ".join(task))
        else:
            # No args, show today's tasks
            ctx.invoke(list_tasks)


@main.command("setup")
@click.option("--force", is_flag=True, help="Force re-setup even if already configured")
def setup(force: bool) -> None:
    """Set up the data directory (run this first!).
    
    Creates the git worktree at ~/.lab-agent/data with template files.
    This command is also run automatically on first use of any other command.
    """
    if is_setup_complete() and not force:
        click.echo("Setup already complete!")
        click.echo(f"  Data directory: {get_data_dir()}")
        click.echo("\nUse --force to re-run setup.")
        return
    
    if run_setup():
        sys.exit(0)
    else:
        sys.exit(1)


@main.command("add")
@click.argument("task")
@click.option("-p", "--project", help="Add to specific project")
def add(task: str, project: str | None) -> None:
    """Add a task to inbox or a specific project."""
    if not ensure_setup():
        sys.exit(1)
    
    data_dir = get_data_dir()
    git_sync_before(data_dir)
    
    if project:
        prompt = f"Add this task to project '{project}': {task}"
    else:
        prompt = f"Add this task to inbox.md: {task}"
    
    invoke_gemini(data_dir, prompt)
    git_sync_after(data_dir, task)


@main.command("list")
@click.option("--today", is_flag=True, help="Only items due today")
@click.option("--week", is_flag=True, help="Items due within 7 days")
@click.option("-p", "--project", help="Filter by project")
@click.option("--waiting", is_flag=True, help="Show @waiting items")
@click.option("--overdue", is_flag=True, help="Show overdue items")
@click.option("--all", "show_all", is_flag=True, help="Show all open tasks")
def list_tasks(
    today: bool,
    week: bool,
    project: str | None,
    waiting: bool,
    overdue: bool,
    show_all: bool,
) -> None:
    """List tasks with various filters."""
    if not ensure_setup():
        sys.exit(1)
    
    data_dir = get_data_dir()
    git_sync_before(data_dir)
    
    # Build the prompt based on options
    filters = []
    if today:
        filters.append("due today")
    if week:
        filters.append("due within the next 7 days")
    if project:
        filters.append(f"in project '{project}'")
    if waiting:
        filters.append("with @waiting tags")
    if overdue:
        filters.append("that are overdue")
    if show_all:
        filters.append("(all open tasks)")
    
    if filters:
        prompt = f"List tasks {' '.join(filters)}"
    else:
        prompt = "List today's tasks and any urgent items"
    
    invoke_gemini(data_dir, prompt)


@main.command("brief")
@click.option("--since", default="yesterday", help="Lookback period")
@click.option("--waiting", is_flag=True, help="Focus on who you're waiting on")
@click.option("--deadlines", is_flag=True, help="Focus on upcoming deadlines")
@click.option("--format", "fmt", type=click.Choice(["text", "markdown", "json"]), default="text")
def brief(since: str, waiting: bool, deadlines: bool, fmt: str) -> None:
    """Generate a daily briefing."""
    if not ensure_setup():
        sys.exit(1)
    
    data_dir = get_data_dir()
    git_sync_before(data_dir)
    
    focus = []
    if waiting:
        focus.append("who I'm waiting on")
    if deadlines:
        focus.append("upcoming deadlines")
    
    focus_str = f" Focus on: {', '.join(focus)}." if focus else ""
    format_str = f" Output in {fmt} format." if fmt != "text" else ""
    
    prompt = f"Generate a morning briefing. Look back {since}.{focus_str}{format_str}"
    
    invoke_gemini(data_dir, prompt)


@main.command("search")
@click.argument("query")
@click.option("--semantic", is_flag=True, help="Use semantic search")
def search(query: str, semantic: bool) -> None:
    """Search across all tasks."""
    if not ensure_setup():
        sys.exit(1)
    
    data_dir = get_data_dir()
    git_sync_before(data_dir)
    
    search_type = "semantic" if semantic else "keyword"
    prompt = f"Search for tasks matching '{query}' using {search_type} search"
    
    invoke_gemini(data_dir, prompt)


@main.command("cleanup")
def cleanup() -> None:
    """Organize inbox by moving tasks to appropriate projects."""
    if not ensure_setup():
        sys.exit(1)
    
    data_dir = get_data_dir()
    git_sync_before(data_dir)
    
    prompt = "Review inbox.md and organize tasks by moving them to appropriate project files based on their content"
    
    invoke_gemini(data_dir, prompt)
    git_sync_after(data_dir, "organize inbox")


@main.command("undo")
@click.argument("count", default=1, type=int)
def undo(count: int) -> None:
    """Undo the last N operations (default: 1)."""
    if not ensure_setup():
        sys.exit(1)
    
    data_dir = get_data_dir()
    
    try:
        # Get the commits we're about to undo
        result = subprocess.run(
            ["git", "log", f"-{count}", "--pretty=%s"],
            cwd=data_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        actions = result.stdout.strip().split('\n')
        
        # Revert each commit in order
        for i in range(count):
            subprocess.run(
                ["git", "revert", "--no-edit", f"HEAD~{i}"],
                cwd=data_dir,
                check=True,
                capture_output=True,
            )
        
        # Rebuild index
        try:
            rebuild_index(data_dir)
            subprocess.run(
                ["git", "add", "-A"],
                cwd=data_dir,
                capture_output=True,
            )
            subprocess.run(
                ["git", "commit", "--amend", "--no-edit"],
                cwd=data_dir,
                capture_output=True,
            )
        except Exception:
            pass
        
        # Push the reverts
        subprocess.run(
            ["git", "push", "--quiet"],
            cwd=data_dir,
            capture_output=True,
        )
        
        for action in actions:
            click.echo(f"Undone: {action}")
    except subprocess.CalledProcessError:
        click.echo("Failed to undo. There may be nothing to undo, or a conflict occurred.", err=True)


@main.command("history")
@click.option("-n", "--count", default=5, help="Number of entries to show")
def history(count: int) -> None:
    """Show recent operations."""
    if not ensure_setup():
        sys.exit(1)
    
    data_dir = get_data_dir()
    
    result = subprocess.run(
        ["git", "log", f"-{count}", "--pretty=format:%h  %s  (%ar)"],
        cwd=data_dir,
        capture_output=True,
        text=True,
    )
    
    if result.stdout.strip():
        click.echo("Recent operations:")
        click.echo(result.stdout)
    else:
        click.echo("No history found.")


@main.command("reset")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
def reset(force: bool) -> None:
    """Reset to last synced state (discards local changes)."""
    if not ensure_setup():
        sys.exit(1)
    
    data_dir = get_data_dir()
    
    if not force:
        click.confirm(
            "This will discard all local changes and reset to the last synced state. Continue?",
            abort=True,
        )
    
    try:
        # Abort any in-progress operations
        subprocess.run(
            ["git", "revert", "--abort"],
            cwd=data_dir,
            capture_output=True,
        )
        subprocess.run(
            ["git", "merge", "--abort"],
            cwd=data_dir,
            capture_output=True,
        )
        subprocess.run(
            ["git", "rebase", "--abort"],
            cwd=data_dir,
            capture_output=True,
        )
        
        # Fetch latest from remote
        subprocess.run(
            ["git", "fetch", "origin"],
            cwd=data_dir,
            capture_output=True,
        )
        
        # Get current branch name
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=data_dir,
            capture_output=True,
            text=True,
        )
        branch = result.stdout.strip() or "data"
        
        # Hard reset to remote
        subprocess.run(
            ["git", "reset", "--hard", f"origin/{branch}"],
            cwd=data_dir,
            check=True,
            capture_output=True,
        )
        
        click.echo("Reset complete. Local state now matches remote.")
    except subprocess.CalledProcessError:
        click.echo("Reset failed. You may need to manually fix the data directory.", err=True)


if __name__ == "__main__":
    main()
