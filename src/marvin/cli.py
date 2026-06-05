"""Marvin CLI - A thin wrapper around Gemini CLI with Git sync."""

import subprocess
import sys
import shutil
import threading
import time
from pathlib import Path

import click

from marvin.index_schema import rebuild_index
from marvin.task_schema import validate_all_task_files
from marvin import fast_path
from marvin import llm_parse
from marvin import styles

# Default data directory: worktree checked out to ~/.marvin/data
DEFAULT_DATA_DIR = Path.home() / ".marvin" / "data"

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
    """Find the main marvin repository (where the CLI was installed from)."""
    # Try common locations
    candidates = [
        TEMPLATE_DIR.parent,  # Adjacent to installed package
        Path.home() / "marvin",
        Path.home() / "code" / "marvin",
        Path.home() / "projects" / "marvin",
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
        click.echo("Error: Could not find the main marvin repository.", err=True)
        click.echo("Please run this command from the marvin repo directory,", err=True)
        click.echo("or set LA_REPO_DIR to point to it.", err=True)
        return False
    
    template_dir = main_repo / "data-template"
    if not template_dir.exists():
        click.echo(f"Error: Template directory not found at {template_dir}", err=True)
        return False
    
    click.echo(f"Setting up marvin data directory at {data_dir}...")
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
    
    click.echo("Marvin data directory not found. Running first-time setup...\n")
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
            styles.console.print("\n[dim]☁️  Synced changes[/dim]")
            return True
        return False
    except subprocess.CalledProcessError as e:
        click.echo(f"Warning: git sync failed: {e}", err=True)
        return False


def validate_after_llm(data_dir: Path) -> bool:
    """Validate all JSON task files after LLM edits.
    
    Returns True if all files are valid. If invalid, reverts changes
    and returns False.
    """
    errors = validate_all_task_files(data_dir)
    
    if errors:
        click.echo("\n❌ LLM produced invalid JSON:", err=True)
        for path, error in errors:
            rel_path = path.relative_to(data_dir)
            click.echo(f"\n  {rel_path}:", err=True)
            # Show first few lines of error
            for line in str(error).split('\n')[:5]:
                click.echo(f"    {line}", err=True)
        
        # Revert changes
        click.echo("\nReverting changes...", err=True)
        subprocess.run(
            ["git", "checkout", "."],
            cwd=data_dir,
            capture_output=True,
        )
        return False
    
    return True


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
    
    # Patterns to filter from output (both stdout and stderr)
    noise_patterns = [
        "Thinking...",
        "status: 503",
        "ApiError:",
        "at async",
        "at throwErrorIfNotOK",
        "at process.processTicksAndRejections",
        "Retrying with backoff",
        "Tool execution denied",
        'Tool "',
        "not found in registry",
        "[ERROR]",
        "node_modules/@google",
        "Attempt ",
        "[Routing]",
        "ClassifierStrategy",
        "Max attempts reached",
        "I will ",  # Filter LLM thinking-out-loud
    ]
    
    # Spinner character pattern (Unicode braille)
    spinner_chars = set("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
    
    def is_noise(line: str) -> bool:
        """Check if a line is noisy output that should be filtered."""
        stripped = line.strip()
        # Filter empty lines
        if not stripped:
            return True
        # Filter lines starting with spinner chars
        if stripped and stripped[0] in spinner_chars:
            return True
        # Filter known noise patterns
        return any(pattern in line for pattern in noise_patterns)
    
    try:
        # Start spinner in background
        spinner_thread = threading.Thread(target=spinner, daemon=True)
        spinner_thread.start()
        
        # Capture both stdout and stderr to filter noise
        result = subprocess.run(
            ["gemini", prompt],
            cwd=data_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        
        # Stop spinner
        stop_spinner.set()
        spinner_thread.join(timeout=0.5)
        
        # Filter and display non-noisy stdout
        if result.stdout:
            clean_lines = [
                line for line in result.stdout.splitlines()
                if not is_noise(line)
            ]
            if clean_lines:
                click.echo("\n".join(clean_lines))
        
        # Filter and display non-noisy stderr (errors only)
        if result.stderr:
            for line in result.stderr.splitlines():
                if not is_noise(line):
                    click.echo(line, err=True)
        
        return result.returncode
    except FileNotFoundError:
        stop_spinner.set()
        click.echo("Error: 'gemini' CLI not found. Please install the Gemini CLI.", err=True)
        return 1


class FreeTextGroup(click.Group):
    """Custom Click group that routes unrecognized subcommands as free text."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        # If the first arg isn't a known command and isn't a flag, treat as free text
        if args and args[0] not in self.commands and not args[0].startswith("-"):
            ctx.ensure_object(dict)
            ctx.obj["free_text"] = " ".join(args)
            ctx.invoked_subcommand = "*"  # Prevent default invoke
            return []
        return super().parse_args(ctx, args)

    def invoke(self, ctx: click.Context) -> None:
        free_text = (ctx.ensure_object(dict)).get("free_text")
        if free_text:
            handle_free_text(free_text)
            return
        return super().invoke(ctx)


def handle_free_text(text: str) -> None:
    """Interpret free-text commands and dispatch to fast-path handlers."""
    if not ensure_setup():
        sys.exit(1)

    data_dir = get_data_dir()
    git_sync_before(data_dir)

    # Detect intent: remove / delete
    words = text.split()
    intent_word = words[0].lower() if words else ""

    if intent_word in ("remove", "delete", "rm"):
        # Remaining words form the search query, dropping filler like "all"
        query_words = [w for w in words[1:] if w.lower() != "all"]
        if not query_words:
            styles.print_error("Remove what? Provide a search term.")
            styles.console.print('[dim]Example: marvin remove all webinar[/dim]')
            sys.exit(1)

        query = " ".join(query_words)
        matches = fast_path.search_tasks_by_query(data_dir, query)

        if not matches:
            styles.console.print(f"[dim]No open tasks matching '{query}'.[/dim]")
            return

        # Show what will be removed
        styles.console.print()
        styles.console.print(
            f"[bold]Found {len(matches)} task(s) matching[/bold] "
            f"[bold cyan]'{query}'[/bold cyan][bold]:[/bold]"
        )
        styles.console.print()
        for task in matches:
            styles.console.print(styles.format_task_rich(task, show_all_tags=True))
        styles.console.print()

        # Batch confirmation
        click.confirm(
            f"Remove all {len(matches)} matching task(s)?",
            abort=True,
        )

        removed = fast_path.remove_tasks_batch(
            data_dir, [t.id for t in matches]
        )
        styles.print_success(f"Removed {len(removed)} task(s).")

        git_sync_after(data_dir, f"remove {len(removed)} '{query}' tasks")
    else:
        styles.print_error(f"Unknown command: {text}")
        styles.console.print("[dim]Try: marvin --help[/dim]")
        sys.exit(1)


@click.group(cls=FreeTextGroup, invoke_without_command=True)
@click.pass_context
def main(ctx: click.Context) -> None:
    """Marvin - Git-backed task assistant.
    
    Quick capture: marvin add "remind me to check Sarah's draft"
    
    Annotate:     marvin note ae23 "see shared doc"
    
    First time? Run: marvin setup
    """
    if ctx.invoked_subcommand is None:
        # No subcommand and no args, show today's tasks
        ctx.invoke(list_tasks)


@main.command("setup")
@click.option("--force", is_flag=True, help="Force re-setup even if already configured")
def setup(force: bool) -> None:
    """Set up the data directory (run this first!).
    
    Creates the git worktree at ~/.marvin/data with template files.
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
@click.option("-u", "--under", "--parent", "parent_id", help="Parent task ID (creates subtask)")
@click.option("--no-llm", is_flag=True, help="Skip LLM, use regex parsing only (faster)")
def add(task: str, parent_id: str | None, no_llm: bool) -> None:
    """Add a task (hybrid: LLM parses, Python writes).
    
    Examples:
    
      marvin add "remind me to check Sarah's draft"
      
      marvin add "run ablation study" --parent ae23
      
      marvin add "prepare slides" -u ae23
    """
    if not ensure_setup():
        sys.exit(1)
    
    data_dir = get_data_dir()
    git_sync_before(data_dir)
    
    try:
        # Use hybrid approach: LLM parses NL, Python writes file
        new_task = llm_parse.add_task(
            data_dir,
            task,
            use_llm=not no_llm,
            parent_id=parent_id,
        )

        # Auto-link waiting_on to a known collaborator
        if new_task.waiting_on:
            canonical, suggestions = fast_path.resolve_waiting_on(data_dir, new_task.waiting_on)
            if canonical and canonical != new_task.waiting_on:
                # Silently rewrite to canonical name
                fast_path.edit_task(data_dir, new_task.id, set_waiting=canonical)
                new_task.waiting_on = canonical
            elif not canonical and suggestions:
                styles.console.print()
                styles.console.print(
                    f"[dim]Waiting on '[/dim][waiting]{new_task.waiting_on}[/waiting][dim]' "
                    f"— did you mean a known collaborator?[/dim]"
                )
                for i, s in enumerate(suggestions, 1):
                    meta = f" ({s.role})" if s.role else ""
                    styles.console.print(f"  [dim]{i}.[/dim] [person.name]{s.name}[/person.name]{meta}")
                styles.console.print(f"  [dim]0.[/dim] Keep '[waiting]{new_task.waiting_on}[/waiting]' as-is")
                choice_raw = click.prompt(
                    "  Choose", default="0", show_default=False
                )
                try:
                    choice = int(choice_raw)
                    if 1 <= choice <= len(suggestions):
                        chosen = suggestions[choice - 1]
                        fast_path.edit_task(data_dir, new_task.id, set_waiting=chosen.name)
                        new_task.waiting_on = chosen.name
                except (ValueError, IndexError):
                    pass  # keep as-is

        if parent_id:
            styles.print_success(f"Added subtask: {new_task.description}")
        else:
            styles.print_success(f"Added: {new_task.description}")

        if new_task.tags:
            styles.console.print(styles.format_tags(new_task.tags))
        if new_task.deadline:
            styles.console.print(styles.format_deadline(new_task.deadline))
        if new_task.waiting_on:
            styles.console.print(styles.format_waiting(new_task.waiting_on))
    except Exception as e:
        styles.print_error(f"Error adding task: {e}")
        sys.exit(1)
    
    git_sync_after(data_dir, task)


@main.command("research")
@click.argument("query")
def research(query: str) -> None:
    """Search the web for deadlines and create/update tasks.
    
    If a deadline with the same match_key already exists, it will be
    updated with new information rather than duplicated.
    
    Pass a URL to extract deadlines directly from a page:
    
      marvin research https://icml.cc/Conferences/2026
    
    Or a search query to search the web:
    
      marvin research "ICML 2026 deadlines"
      
      marvin research "NeurIPS 2026 submission dates"
    """
    if not ensure_setup():
        sys.exit(1)
    
    data_dir = get_data_dir()
    git_sync_before(data_dir)
    
    url = None
    if llm_parse.is_url(query):
        url = query
        styles.console.print(f"[bold cyan]🌐 Fetching:[/bold cyan] {url}...")
    else:
        styles.console.print(f"[bold cyan]🔍 Searching:[/bold cyan] {query}...")
    
    try:
        created, updated = llm_parse.research_and_add_tasks(
            data_dir,
            query,
            url=url,
        )
        
        if created or updated:
            if created:
                styles.console.print(f"\n[green]Added {len(created)} new deadline(s):[/green]")
                for task in created:
                    styles.print_success(f"Added: {task.description}")
                    if task.deadline:
                        styles.console.print(styles.format_deadline(
                            task.deadline, 
                            deadline_time=task.deadline_time
                        ))
            
            if updated:
                styles.console.print(f"\n[yellow]Updated {len(updated)} existing deadline(s):[/yellow]")
                for task in updated:
                    styles.console.print(f"  [dim]•[/dim] {task.description}")
                    if task.deadline:
                        styles.console.print(styles.format_deadline(
                            task.deadline,
                            deadline_time=task.deadline_time
                        ))
        else:
            styles.console.print("\n[dim]No deadlines found. Try a more specific query.[/dim]")
            return
            
    except Exception as e:
        styles.print_error(f"Error: {e}")
        sys.exit(1)
    
    git_sync_after(data_dir, f"research: {query[:30]}")


@main.command("list")
@click.option("--today", is_flag=True, help="Only items due today")
@click.option("--week", is_flag=True, help="Items due within 7 days")
@click.option("-t", "--tag", help="Filter by tag (e.g., 'conference' or '#conference')")
@click.option("--waiting", is_flag=True, help="Show @waiting items")
@click.option("--overdue", is_flag=True, help="Show overdue items")
@click.option("--all", "show_all", is_flag=True, help="Show all open tasks")
@click.option("--raw", is_flag=True, help="Show all tasks with full tags (for debugging)")
def list_tasks(
    today: bool,
    week: bool,
    tag: str | None,
    waiting: bool,
    overdue: bool,
    show_all: bool,
    raw: bool,
) -> None:
    """List tasks with various filters (fast path)."""
    if not ensure_setup():
        sys.exit(1)
    
    data_dir = get_data_dir()
    git_sync_before(data_dir)
    
    # Strip # from tag if present
    if tag and tag.startswith('#'):
        tag = tag[1:]
    
    # Use fast path - pure Python, no LLM
    auto_cleared = fast_path.list_tasks(
        data_dir,
        tag=tag,
        waiting=waiting,
        overdue=overdue,
        week=week,
        today=today,
        show_all=show_all,
        raw=raw,
    )
    
    # Sync if any conference deadlines were auto-cleared
    if auto_cleared:
        git_sync_after(data_dir, "auto-clear past conference deadlines")


@main.command("brief")
@click.option("--since", default="yesterday", help="Lookback period (ignored in fast mode)")
@click.option("--waiting", is_flag=True, help="Focus on who you're waiting on")
@click.option("--deadlines", is_flag=True, help="Focus on upcoming deadlines")
@click.option("--format", "fmt", type=click.Choice(["text", "markdown", "json"]), default="text")
def brief(since: str, waiting: bool, deadlines: bool, fmt: str) -> None:
    """Generate a daily briefing (fast path)."""
    if not ensure_setup():
        sys.exit(1)
    
    data_dir = get_data_dir()
    git_sync_before(data_dir)
    
    # Use fast path - pure Python, no LLM
    auto_cleared = fast_path.show_brief(data_dir, waiting_focus=waiting)
    
    # Sync if any conference deadlines were auto-cleared
    if auto_cleared:
        git_sync_after(data_dir, "auto-clear past conference deadlines")


@main.command("search")
@click.argument("query")
@click.option("--semantic", is_flag=True, help="Use semantic search (requires LLM)")
def search(query: str, semantic: bool) -> None:
    """Search across all tasks."""
    if not ensure_setup():
        sys.exit(1)
    
    data_dir = get_data_dir()
    git_sync_before(data_dir)
    
    if semantic:
        # Semantic search requires LLM
        prompt = f"Search for tasks matching '{query}' using semantic search"
        invoke_gemini(data_dir, prompt)
    else:
        # Keyword search uses fast path
        fast_path.search_tasks(data_dir, query)


@main.command("subtasks")
@click.argument("task_id")
def subtasks(task_id: str) -> None:
    """List subtasks of a task.
    
    Use the 4-character ID shown in 'la list' output.
    
    Example:
    
      marvin subtasks ae23
    """
    if not ensure_setup():
        sys.exit(1)
    
    data_dir = get_data_dir()
    git_sync_before(data_dir)
    
    result = fast_path.find_task_by_id(data_dir, task_id)
    if result is None:
        styles.print_error(f"Task '{task_id}' not found.")
        sys.exit(1)
    
    file_path, task_file, parent_task = result
    children = task_file.get_children(parent_task.id)
    
    if not children:
        styles.console.print(f"[dim]No subtasks for '{parent_task.description}'.[/dim]")
        return
    
    styles.console.print()
    styles.console.print(f"[bold]Subtasks of[/bold] [{parent_task.id[:4]}] {parent_task.description}:")
    styles.console.print()
    
    # Print the parent and all its subtasks as a tree
    fast_path.print_task_with_subtasks(task_file, parent_task)



@main.command("edit")
@click.argument("task_id")
@click.option("--add-tag", "-a", multiple=True, help="Add a tag")
@click.option("--remove-tag", "-r", multiple=True, help="Remove a tag")
@click.option("--deadline", "-d", help="Set deadline (YYYY-MM-DD)")
@click.option("--no-deadline", is_flag=True, help="Clear deadline")
@click.option("--priority", "-p", type=click.Choice(["high", "medium", "low"]), help="Set priority")
@click.option("--waiting", "-w", help="Set waiting-on person")
@click.option("--no-waiting", is_flag=True, help="Clear waiting-on")
@click.option("--description", help="Set new description")
def edit(
    task_id: str,
    add_tag: tuple[str, ...],
    remove_tag: tuple[str, ...],
    deadline: str | None,
    no_deadline: bool,
    priority: str | None,
    waiting: str | None,
    no_waiting: bool,
    description: str | None,
) -> None:
    """Edit a task by ID (fast path).
    
    Use the 4-character ID shown in 'la list' output.
    
    Examples:
    
      marvin edit ae23 --add-tag conference
      
      marvin edit ae23 -a paper -a deadline
      
      marvin edit ae23 --deadline 2026-02-15
      
      marvin edit ae23 --priority high
    """
    if not ensure_setup():
        sys.exit(1)
    
    data_dir = get_data_dir()
    git_sync_before(data_dir)
    
    task = fast_path.edit_task(
        data_dir,
        task_id,
        add_tags=list(add_tag) if add_tag else None,
        remove_tags=list(remove_tag) if remove_tag else None,
        set_deadline=deadline,
        clear_deadline=no_deadline,
        set_priority=priority,
        set_waiting=waiting,
        clear_waiting=no_waiting,
        set_description=description,
    )
    
    if task is None:
        styles.print_error(f"Task '{task_id}' not found.")
        sys.exit(1)
    
    styles.print_success(f"Updated: [{task.id[:4]}] {task.description}")
    if task.deadline:
        styles.console.print(styles.format_deadline(task.deadline))
    if task.waiting_on:
        styles.console.print(styles.format_waiting(task.waiting_on))
    if task.tags:
        styles.console.print(styles.format_tags(task.tags))
    
    git_sync_after(data_dir, f"edit {task_id}")


@main.command("note")
@click.argument("task_id")
@click.argument("text")
def note(task_id: str, text: str) -> None:
    """Add a note to a task by ID (fast path).

    Notes appear as indented lines below the task in 'la list'.

    Examples:

      marvin note ae23 "outline in shared Overleaf doc"

      marvin note ae23 "waiting for Bob's figure"
    """
    if not ensure_setup():
        sys.exit(1)

    data_dir = get_data_dir()
    git_sync_before(data_dir)

    task = fast_path.add_note(data_dir, task_id, text)

    if task is None:
        styles.print_error(f"Task '{task_id}' not found.")
        sys.exit(1)

    styles.print_success(f"Note added to [{task.id[:4]}] {task.description}")
    styles.console.print(styles.format_note(text))

    git_sync_after(data_dir, f"note {task_id}")


@main.command("done")
@click.argument("task_id")
def done(task_id: str) -> None:
    """Mark a task as done by ID (fast path).
    
    Use the 4-character ID shown in 'la list' output.
    
    Example:
    
      marvin done ae23
    """
    if not ensure_setup():
        sys.exit(1)
    
    data_dir = get_data_dir()
    git_sync_before(data_dir)
    
    task = fast_path.mark_done(data_dir, task_id)
    
    if task is None:
        styles.print_error(f"Task '{task_id}' not found.")
        sys.exit(1)
    
    styles.print_success(f"Done: [{task.id[:4]}] {task.description}")
    
    git_sync_after(data_dir, f"done {task_id}")


@main.command("rm")
@click.argument("task_id")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation prompt")
def rm(task_id: str, force: bool) -> None:
    """Remove a task entirely by ID (fast path).
    
    Use the 4-character ID shown in 'la list' output.
    This permanently removes the task (use 'done' to mark as completed instead).
    
    Example:
    
      marvin rm 72f9
      marvin rm 72f9 --force
    """
    if not ensure_setup():
        sys.exit(1)
    
    data_dir = get_data_dir()
    git_sync_before(data_dir)
    
    # Find the task first to show what we're removing
    result = fast_path.find_task_by_id(data_dir, task_id)
    if result is None:
        styles.print_error(f"Task '{task_id}' not found.")
        sys.exit(1)
    
    _, _, task = result
    
    if not force:
        click.confirm(
            f"Remove '[{task.id[:4]}] {task.description}'?",
            abort=True,
        )
    
    removed = fast_path.remove_task(data_dir, task_id)
    
    if removed is None:
        styles.print_error(f"Task '{task_id}' not found.")
        sys.exit(1)
    
    styles.print_success(f"Removed: [{removed.id[:4]}] {removed.description}")
    
    git_sync_after(data_dir, f"rm {task_id}")


@main.command("clear-overdue")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation prompt")
def clear_overdue(force: bool) -> None:
    """Mark all overdue tasks as done (fast path)."""
    if not ensure_setup():
        sys.exit(1)
    
    data_dir = get_data_dir()
    git_sync_before(data_dir)
    
    # Check if there are any overdue tasks first
    tf = fast_path.load_tasks(data_dir)
    overdue_count = len([t for t in tf.open_tasks if t.is_overdue()])
    
    if overdue_count == 0:
        styles.console.print("[green]✨ No overdue tasks found.[/green]")
        return
        
    if not force:
        click.confirm(
            f"Mark all {overdue_count} overdue tasks as done?",
            abort=True,
        )
    
    cleared = fast_path.clear_overdue_tasks(data_dir)
    
    if cleared:
        styles.print_success(f"Cleared {len(cleared)} overdue tasks.")
        for task in cleared:
            styles.console.print(f"  [dim]•[/dim] {task.description}")
    
    git_sync_after(data_dir, f"clear-overdue ({len(cleared)} tasks)")


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


# ---------------------------------------------------------------------------
# Collaborator commands
# ---------------------------------------------------------------------------

@main.group("person")
def person_group() -> None:
    """Manage collaborators and people.

    Examples:

      marvin person add "Alice Chen" --role "PhD student" --affiliation "MIT CSAIL"

      marvin person list

      marvin person show alice

      marvin person note alice "co-author on NeurIPS 2026"

      marvin person edit alice --role "postdoc" --alias ali

      marvin person rm alice
    """


@person_group.command("add")
@click.argument("name")
@click.option("--role", "-r", help="Role (e.g. 'PhD student', 'collaborator')")
@click.option("--affiliation", "-a", help="Institution or department")
@click.option("--email", "-e", help="Email address")
@click.option("--alias", multiple=True, help="Additional alias (repeatable)")
@click.option("--tag", "-t", multiple=True, help="Tag (repeatable)")
def person_add(
    name: str,
    role: str | None,
    affiliation: str | None,
    email: str | None,
    alias: tuple[str, ...],
    tag: tuple[str, ...],
) -> None:
    """Add a collaborator.

    Auto-aliases are generated from the name (first name, last name).
    Use --alias to add custom shorthand names.

    Examples:

      marvin person add "Alice Chen" --role "PhD student" --affiliation "MIT"

      marvin person add "Bob Smith" --alias bob --alias bsmith --email bob@uni.edu
    """
    if not ensure_setup():
        sys.exit(1)

    data_dir = get_data_dir()
    git_sync_before(data_dir)

    try:
        collab = fast_path.add_collaborator(
            data_dir,
            name,
            role=role,
            affiliation=affiliation,
            email=email,
            extra_aliases=list(alias),
            tags=[t.lstrip("#").lower() for t in tag],
        )
    except ValueError as e:
        styles.print_error(str(e))
        sys.exit(1)

    styles.print_success(f"Added collaborator: {collab.name}  [{collab.id[:4]}]")
    if collab.role:
        styles.console.print(f"  [dim]role:[/dim] [person.role]{collab.role}[/person.role]")
    if collab.affiliation:
        styles.console.print(f"  [dim]affiliation:[/dim] [person.affil]{collab.affiliation}[/person.affil]")
    if collab.email:
        styles.console.print(f"  [dim]email:[/dim] [person.email]{collab.email}[/person.email]")
    all_aliases = collab.all_aliases()
    if all_aliases:
        styles.console.print(f"  [dim]aliases:[/dim] [person.alias]{', '.join(all_aliases)}[/person.alias]")

    git_sync_after(data_dir, f"person add {name}")


@person_group.command("list")
def person_list() -> None:
    """List all collaborators."""
    if not ensure_setup():
        sys.exit(1)

    data_dir = get_data_dir()
    git_sync_before(data_dir)

    cf = fast_path.load_collaborators(data_dir)

    if not cf.collaborators:
        styles.console.print("[dim]No collaborators yet. Add one with: marvin person add \"Name\"[/dim]")
        return

    styles.console.print()
    styles.console.print(f"[bold]Collaborators[/bold] [dim]({len(cf.collaborators)})[/dim]")
    styles.console.print()
    for collab in sorted(cf.collaborators, key=lambda c: c.name.lower()):
        styles.console.print(styles.format_collaborator_row(collab))
    styles.console.print()


@person_group.command("show")
@click.argument("person")
def person_show(person: str) -> None:
    """Show a collaborator profile and their related tasks.

    PERSON can be a name, alias, or 4-char ID prefix.

    Examples:

      marvin person show alice

      marvin person show "Alice Chen"

      marvin person show ae23
    """
    if not ensure_setup():
        sys.exit(1)

    data_dir = get_data_dir()
    git_sync_before(data_dir)

    cf = fast_path.load_collaborators(data_dir)

    from marvin.collaborator_schema import resolve_person
    collab, suggestions = resolve_person(person, cf)

    if collab is None:
        if suggestions:
            styles.print_error(f"No exact match for '{person}'. Did you mean:")
            for s in suggestions:
                meta = f" ({s.role})" if s.role else ""
                styles.console.print(f"  [person.name]{s.name}[/person.name]{meta}  [dim]{s.id[:4]}[/dim]")
        else:
            styles.print_error(f"Collaborator '{person}' not found.")
        sys.exit(1)

    tasks = fast_path.get_tasks_for_person(data_dir, collab)
    ideas = fast_path.get_ideas_for_person(data_dir, collab)
    styles.console.print()
    styles.console.print(styles.format_person_card(collab, tasks, ideas=ideas))


@person_group.command("note")
@click.argument("person")
@click.argument("text")
def person_note(person: str, text: str) -> None:
    """Add a note to a collaborator.

    PERSON can be a name, alias, or 4-char ID prefix.

    Examples:

      marvin person note alice "defended proposal last week"

      marvin person note "Bob Smith" "reviewed chapter 3, feedback pending"
    """
    if not ensure_setup():
        sys.exit(1)

    data_dir = get_data_dir()
    git_sync_before(data_dir)

    collab = fast_path.add_collaborator_note(data_dir, person, text)

    if collab is None:
        # Try fuzzy match and suggest
        cf = fast_path.load_collaborators(data_dir)
        from marvin.collaborator_schema import resolve_person
        _, suggestions = resolve_person(person, cf)
        if suggestions:
            styles.print_error(f"Collaborator '{person}' not found. Did you mean:")
            for s in suggestions:
                styles.console.print(f"  [person.name]{s.name}[/person.name]  [dim]{s.id[:4]}[/dim]")
        else:
            styles.print_error(f"Collaborator '{person}' not found.")
        sys.exit(1)

    styles.print_success(f"Note added to {collab.name}")
    styles.console.print(styles.format_note(text))

    git_sync_after(data_dir, f"person note {collab.name[:20]}")


@person_group.command("edit")
@click.argument("person")
@click.option("--name", "set_name", help="Set new display name")
@click.option("--role", "set_role", help="Set role (empty string to clear)")
@click.option("--affiliation", "set_affiliation", help="Set affiliation (empty string to clear)")
@click.option("--email", "set_email", help="Set email (empty string to clear)")
@click.option("--alias", "add_alias", multiple=True, help="Add alias (repeatable)")
@click.option("--remove-alias", multiple=True, help="Remove alias (repeatable)")
@click.option("--tag", "add_tag", multiple=True, help="Add tag (repeatable)")
@click.option("--remove-tag", multiple=True, help="Remove tag (repeatable)")
def person_edit(
    person: str,
    set_name: str | None,
    set_role: str | None,
    set_affiliation: str | None,
    set_email: str | None,
    add_alias: tuple[str, ...],
    remove_alias: tuple[str, ...],
    add_tag: tuple[str, ...],
    remove_tag: tuple[str, ...],
) -> None:
    """Edit a collaborator's profile.

    PERSON can be a name, alias, or 4-char ID prefix.

    Examples:

      marvin person edit alice --role postdoc

      marvin person edit alice --alias ali --alias alicec

      marvin person edit alice --remove-alias chen
    """
    if not ensure_setup():
        sys.exit(1)

    data_dir = get_data_dir()
    git_sync_before(data_dir)

    collab = fast_path.edit_collaborator(
        data_dir,
        person,
        set_name=set_name,
        set_role=set_role,
        set_affiliation=set_affiliation,
        set_email=set_email,
        add_aliases=list(add_alias) if add_alias else None,
        remove_aliases=list(remove_alias) if remove_alias else None,
        add_tags=[t.lstrip("#").lower() for t in add_tag] if add_tag else None,
        remove_tags=list(remove_tag) if remove_tag else None,
    )

    if collab is None:
        cf = fast_path.load_collaborators(data_dir)
        from marvin.collaborator_schema import resolve_person
        _, suggestions = resolve_person(person, cf)
        if suggestions:
            styles.print_error(f"Collaborator '{person}' not found. Did you mean:")
            for s in suggestions:
                styles.console.print(f"  [person.name]{s.name}[/person.name]  [dim]{s.id[:4]}[/dim]")
        else:
            styles.print_error(f"Collaborator '{person}' not found.")
        sys.exit(1)

    styles.print_success(f"Updated: {collab.name}  [{collab.id[:4]}]")
    if collab.role:
        styles.console.print(f"  [dim]role:[/dim] [person.role]{collab.role}[/person.role]")
    all_aliases = collab.all_aliases()
    if all_aliases:
        styles.console.print(f"  [dim]aliases:[/dim] [person.alias]{', '.join(all_aliases)}[/person.alias]")

    git_sync_after(data_dir, f"person edit {collab.name[:20]}")


@person_group.command("rm")
@click.argument("person")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation prompt")
def person_rm(person: str, force: bool) -> None:
    """Remove a collaborator.

    PERSON can be a name, alias, or 4-char ID prefix.
    This only removes the collaborator record; tasks are not affected.

    Example:

      marvin person rm alice
    """
    if not ensure_setup():
        sys.exit(1)

    data_dir = get_data_dir()
    git_sync_before(data_dir)

    # Find first so we can confirm
    cf = fast_path.load_collaborators(data_dir)
    from marvin.collaborator_schema import resolve_person
    collab, suggestions = resolve_person(person, cf)

    if collab is None:
        if suggestions:
            styles.print_error(f"Collaborator '{person}' not found. Did you mean:")
            for s in suggestions:
                styles.console.print(f"  [person.name]{s.name}[/person.name]  [dim]{s.id[:4]}[/dim]")
        else:
            styles.print_error(f"Collaborator '{person}' not found.")
        sys.exit(1)

    if not force:
        click.confirm(f"Remove collaborator '{collab.name}'?", abort=True)

    fast_path.remove_collaborator(data_dir, collab.id)
    styles.print_success(f"Removed collaborator: {collab.name}")

    git_sync_after(data_dir, f"person rm {collab.name[:20]}")


@main.command("who")
@click.argument("person")
def who(person: str) -> None:
    """Quick look up a collaborator (alias for 'marvin person show').

    PERSON can be a name, alias, or 4-char ID.

    Examples:

      marvin who alice

      marvin who "Bob Smith"
    """
    if not ensure_setup():
        sys.exit(1)

    data_dir = get_data_dir()
    git_sync_before(data_dir)

    cf = fast_path.load_collaborators(data_dir)

    from marvin.collaborator_schema import resolve_person
    collab, suggestions = resolve_person(person, cf)

    if collab is None:
        if suggestions:
            styles.print_error(f"No exact match for '{person}'. Did you mean:")
            for s in suggestions:
                meta = f" ({s.role})" if s.role else ""
                styles.console.print(f"  [person.name]{s.name}[/person.name]{meta}  [dim]{s.id[:4]}[/dim]")
        else:
            styles.print_error(f"Collaborator '{person}' not found.")
            styles.console.print("[dim]Add them with: marvin person add \"Name\"[/dim]")
        sys.exit(1)

    tasks = fast_path.get_tasks_for_person(data_dir, collab)
    ideas = fast_path.get_ideas_for_person(data_dir, collab)
    styles.console.print()
    styles.console.print(styles.format_person_card(collab, tasks, ideas=ideas))


# ---------------------------------------------------------------------------
# Idea commands
# ---------------------------------------------------------------------------

@main.command("idea")
@click.argument("thought")
@click.option("-t", "--tag", multiple=True, help="Add a tag (repeatable)")
@click.option("-s", "--source", help="Where this came from (paper, meeting, etc.)")
@click.option("-p", "--person", multiple=True, help="Related person (repeatable)")
@click.option("-l", "--link", "links", multiple=True, help="URL or reference (repeatable)")
def idea_capture(thought: str, tag: tuple[str, ...], source: str | None,
                 person: tuple[str, ...], links: tuple[str, ...]) -> None:
    """Capture a research idea (creates a spark).

    Quick capture with zero friction. The idea starts as a "spark" and
    will auto-archive after 30 days unless you tend it.

    Examples:

      marvin idea "contrastive pretraining might fix distribution shift"

      marvin idea "shared annotation tool for the lab" -t tooling -s "lab meeting"

      marvin idea "Sarah's dataset could work" --person sarah
    """
    if not ensure_setup():
        sys.exit(1)

    data_dir = get_data_dir()
    git_sync_before(data_dir)

    new_idea = fast_path.add_idea(
        data_dir,
        thought,
        tags=[t.lstrip("#").lower() for t in tag] if tag else None,
        source=source,
        people=list(person) if person else None,
        links=list(links) if links else None,
    )

    styles.print_success(f"Captured: {new_idea.thought}")
    if new_idea.tags:
        styles.console.print(styles.format_tags(new_idea.tags))
    if new_idea.source:
        styles.console.print(f"  [idea.source]{new_idea.source}[/idea.source]")
    if new_idea.people:
        for p in new_idea.people:
            styles.console.print(f"  [waiting]👤 {p}[/waiting]")

    styles.console.print()
    styles.console.print("[dim]Spark created. It will auto-archive in 30 days unless tended.[/dim]")

    git_sync_after(data_dir, f"idea: {thought[:40]}")


class IdeasGroup(click.Group):
    """Custom group that defaults to 'list' when invoked without subcommand."""

    def invoke(self, ctx: click.Context) -> None:
        if ctx.invoked_subcommand is None:
            ctx.invoke(ideas_list)
            return
        return super().invoke(ctx)


@main.group("ideas", cls=IdeasGroup, invoke_without_command=True)
@click.pass_context
def ideas_group(ctx: click.Context) -> None:
    """Browse and curate research ideas.

    Run 'marvin ideas' to list active ideas.
    Run 'marvin ideas tend' to triage expiring ideas.
    """
    pass


@ideas_group.command("list")
@click.option("--sparks", is_flag=True, help="Show only sparks")
@click.option("--developing", is_flag=True, help="Show only developing ideas")
@click.option("--mature", is_flag=True, help="Show only mature ideas")
@click.option("--archived", is_flag=True, help="Show archived ideas")
@click.option("-t", "--tag", help="Filter by tag")
@click.option("--person", help="Filter by person")
def ideas_list(
    sparks: bool,
    developing: bool,
    mature: bool,
    archived: bool,
    tag: str | None,
    person: str | None,
) -> None:
    """List active ideas."""
    if not ensure_setup():
        sys.exit(1)

    data_dir = get_data_dir()
    git_sync_before(data_dir)

    # Run decay first
    just_archived, warning = fast_path.run_idea_decay(data_dir)

    if just_archived:
        for idea in just_archived:
            styles.console.print(f"[dim]Auto-archived: {idea.thought}[/dim]")
        styles.console.print()
        git_sync_after(data_dir, f"auto-archive {len(just_archived)} ideas")

    idea_file = fast_path.load_ideas(data_dir)

    # Determine which ideas to show
    if archived:
        ideas = [i for i in idea_file.ideas if i.status == "archived"]
        label = "Archived Ideas"
    elif sparks:
        ideas = idea_file.sparks
        label = "Sparks"
    elif developing:
        ideas = idea_file.developing_ideas
        label = "Developing Ideas"
    elif mature:
        ideas = idea_file.mature_ideas
        label = "Mature Ideas"
    else:
        ideas = idea_file.active_ideas
        label = "Active Ideas"

    # Apply filters
    if tag:
        tag_lower = tag.lstrip("#").lower()
        ideas = [i for i in ideas if tag_lower in [t.lower() for t in i.tags]]
    if person:
        person_lower = person.lower()
        ideas = [i for i in ideas if any(p.lower() == person_lower for p in i.people)]

    if not ideas:
        styles.console.print(f"[dim]No {label.lower()} found.[/dim]")
        if not archived:
            styles.console.print("[dim]Capture one with: marvin idea \"your thought\"[/dim]")
        return

    styles.console.print()
    styles.console.print(f"[bold]💡 {label}[/bold] [dim]({len(ideas)})[/dim]")
    styles.console.print()

    for idea in ideas:
        styles.console.print(styles.format_idea_rich(idea))
        styles.console.print()


@ideas_group.command("show")
@click.argument("idea_id")
def ideas_show(idea_id: str) -> None:
    """Show full details for an idea.

    Example:

      marvin ideas show ae23
    """
    if not ensure_setup():
        sys.exit(1)

    data_dir = get_data_dir()
    git_sync_before(data_dir)

    result = fast_path.find_idea_by_id(data_dir, idea_id)
    if result is None:
        styles.print_error(f"Idea '{idea_id}' not found.")
        sys.exit(1)

    _, _, idea = result
    styles.console.print()
    styles.console.print(styles.format_idea_card(idea))


@ideas_group.command("search")
@click.argument("query")
def ideas_search(query: str) -> None:
    """Search across all ideas (including archived).

    Example:

      marvin ideas search "contrastive"
    """
    if not ensure_setup():
        sys.exit(1)

    data_dir = get_data_dir()
    git_sync_before(data_dir)

    fast_path.search_ideas(data_dir, query)


@ideas_group.command("note")
@click.argument("idea_id")
@click.argument("text")
def ideas_note(idea_id: str, text: str) -> None:
    """Add a note to an idea (resets decay clock).

    Adding a note is a deliberate act of tending — it resets the
    auto-archive countdown.

    Examples:

      marvin ideas note ae23 "connects to Bob's pretraining work"

      marvin ideas note ae23 "Sarah confirmed this approach works"
    """
    if not ensure_setup():
        sys.exit(1)

    data_dir = get_data_dir()
    git_sync_before(data_dir)

    idea = fast_path.add_idea_note(data_dir, idea_id, text)
    if idea is None:
        styles.print_error(f"Idea '{idea_id}' not found.")
        sys.exit(1)

    styles.print_success(f"Note added to [{idea.id[:4]}]")
    styles.console.print(styles.format_note(text))
    remaining = idea.days_until_archive()
    if remaining is not None:
        styles.console.print(f"[dim]  Decay clock reset ({remaining}d remaining)[/dim]")

    git_sync_after(data_dir, f"idea note {idea_id}")


@ideas_group.command("tag")
@click.argument("idea_id")
@click.argument("tags", nargs=-1, required=True)
def ideas_tag(idea_id: str, tags: tuple[str, ...]) -> None:
    """Add tags to an idea.

    Example:

      marvin ideas tag ae23 transfer-learning ml
    """
    if not ensure_setup():
        sys.exit(1)

    data_dir = get_data_dir()
    git_sync_before(data_dir)

    idea = fast_path.edit_idea(
        data_dir, idea_id,
        add_tags=[t.lstrip("#").lower() for t in tags],
    )
    if idea is None:
        styles.print_error(f"Idea '{idea_id}' not found.")
        sys.exit(1)

    styles.print_success(f"Updated: [{idea.id[:4]}]")
    styles.console.print(styles.format_tags(idea.tags))

    git_sync_after(data_dir, f"idea tag {idea_id}")


@ideas_group.command("link")
@click.argument("idea_id")
@click.option("--person", "-p", help="Link to a person")
@click.option("--task", "-t", "task_id", help="Link to a task by ID")
@click.option("--idea", "-i", "other_idea_id", help="Link to another idea by ID")
@click.option("--url", "-u", help="Link to a URL")
def ideas_link(idea_id: str, person: str | None, task_id: str | None,
               other_idea_id: str | None, url: str | None) -> None:
    """Link an idea to a person, task, idea, or URL.

    Examples:

      marvin ideas link ae23 --person sarah

      marvin ideas link ae23 --task bf91

      marvin ideas link ae23 --url https://arxiv.org/abs/2026.12345
    """
    if not ensure_setup():
        sys.exit(1)

    if not any([person, task_id, other_idea_id, url]):
        styles.print_error("Provide at least one link: --person, --task, --idea, or --url")
        sys.exit(1)

    data_dir = get_data_dir()
    git_sync_before(data_dir)

    idea = fast_path.link_idea(
        data_dir, idea_id,
        task_id=task_id,
        other_idea_id=other_idea_id,
        person=person,
        url=url,
    )
    if idea is None:
        styles.print_error(f"Idea '{idea_id}' not found (or linked target not found).")
        sys.exit(1)

    styles.print_success(f"Updated links for [{idea.id[:4]}]")

    git_sync_after(data_dir, f"idea link {idea_id}")


@ideas_group.command("develop")
@click.argument("idea_id")
@click.option("--note", "-n", "note_text", help="Note explaining why this is worth keeping")
def ideas_develop(idea_id: str, note_text: str | None) -> None:
    """Promote a spark to developing (requires a note).

    This is a deliberate act of retention — you must explain why
    this idea is worth keeping.

    Example:

      marvin ideas develop ae23 -n "connects to our grant proposal"
    """
    if not ensure_setup():
        sys.exit(1)

    if not note_text:
        note_text = click.prompt("Why is this idea worth keeping?")

    data_dir = get_data_dir()
    git_sync_before(data_dir)

    idea = fast_path.develop_idea(data_dir, idea_id, note_text)
    if idea is None:
        styles.print_error(f"Idea '{idea_id}' not found or not a spark.")
        sys.exit(1)

    styles.print_success(f"Developed: [{idea.id[:4]}] {idea.thought}")
    styles.console.print("[dim]  spark → developing (90-day decay clock started)[/dim]")

    git_sync_after(data_dir, f"idea develop {idea_id}")


@ideas_group.command("mature")
@click.argument("idea_id")
@click.option("--note", "-n", "note_text", help="Note on what this could become")
def ideas_mature(idea_id: str, note_text: str | None) -> None:
    """Promote a developing idea to mature (requires a note).

    Mature ideas have no decay. Explain what this idea could become.

    Example:

      marvin ideas mature ae23 -n "ready to become a project proposal"
    """
    if not ensure_setup():
        sys.exit(1)

    if not note_text:
        note_text = click.prompt("What could this idea become?")

    data_dir = get_data_dir()
    git_sync_before(data_dir)

    idea = fast_path.mature_idea(data_dir, idea_id, note_text)
    if idea is None:
        styles.print_error(f"Idea '{idea_id}' not found or not developing.")
        sys.exit(1)

    styles.print_success(f"Matured: [{idea.id[:4]}] {idea.thought}")
    styles.console.print("[dim]  developing → mature (no longer decays)[/dim]")

    git_sync_after(data_dir, f"idea mature {idea_id}")


@ideas_group.command("promote")
@click.argument("idea_id")
@click.option("--deadline", "-d", help="Set deadline on the new task (YYYY-MM-DD)")
@click.option("--parent", "-u", "parent_id", help="Parent task ID for the new task")
@click.option("--waiting", "-w", help="Set waiting-on for the new task")
def ideas_promote(idea_id: str, deadline: str | None, parent_id: str | None,
                  waiting: str | None) -> None:
    """Graduate an idea into a task.

    The idea is archived with a link to the new task.

    Examples:

      marvin ideas promote ae23

      marvin ideas promote ae23 --deadline 2026-09-01
    """
    if not ensure_setup():
        sys.exit(1)

    data_dir = get_data_dir()
    git_sync_before(data_dir)

    result = fast_path.promote_idea(
        data_dir, idea_id,
        deadline=deadline,
        parent_id=parent_id,
        waiting=waiting,
    )
    if result is None:
        styles.print_error(f"Idea '{idea_id}' not found or already archived/promoted.")
        sys.exit(1)

    idea, task = result
    styles.print_success(f"Promoted idea [{idea.id[:4]}] → task [{task.id[:4]}]")
    styles.console.print(f"  [dim]Task:[/dim] {task.description}")
    if task.deadline:
        styles.console.print(styles.format_deadline(task.deadline))
    if task.tags:
        styles.console.print(styles.format_tags(task.tags))

    git_sync_after(data_dir, f"promote idea {idea_id}")


@ideas_group.command("archive")
@click.argument("idea_id")
def ideas_archive(idea_id: str) -> None:
    """Archive an idea (intentional composting).

    Archived ideas are still searchable via 'marvin ideas search'.

    Example:

      marvin ideas archive ae23
    """
    if not ensure_setup():
        sys.exit(1)

    data_dir = get_data_dir()
    git_sync_before(data_dir)

    idea = fast_path.archive_idea(data_dir, idea_id)
    if idea is None:
        styles.print_error(f"Idea '{idea_id}' not found.")
        sys.exit(1)

    styles.print_success(f"Archived: [{idea.id[:4]}] {idea.thought}")

    git_sync_after(data_dir, f"idea archive {idea_id}")


@ideas_group.command("tend")
def ideas_tend() -> None:
    """Triage ideas approaching auto-archive.

    For each expiring idea, choose to:
    - Keep it (add a note explaining why)
    - Archive it (intentional composting)
    - Skip it (clock keeps ticking)
    """
    if not ensure_setup():
        sys.exit(1)

    data_dir = get_data_dir()
    git_sync_before(data_dir)

    # Run decay first
    just_archived, _ = fast_path.run_idea_decay(data_dir)
    if just_archived:
        for idea in just_archived:
            styles.console.print(f"[dim]Auto-archived: {idea.thought}[/dim]")
        styles.console.print()

    needs_attention = fast_path.get_ideas_needing_attention(data_dir)

    if not needs_attention:
        styles.console.print("[green]🌱 All ideas are well-tended. Nothing needs attention.[/green]")
        if just_archived:
            git_sync_after(data_dir, f"auto-archive {len(just_archived)} ideas")
        return

    styles.console.print()
    styles.console.print(
        f"[bold]🌱 Garden Triage[/bold] [dim]— "
        f"{len(needs_attention)} idea{'s' if len(needs_attention) != 1 else ''} "
        f"need{'s' if len(needs_attention) == 1 else ''} attention[/dim]"
    )
    styles.console.print()

    tended_count = 0
    archived_count = 0

    for idea in needs_attention:
        remaining = idea.days_until_archive()
        remaining_str = f"{remaining}d" if remaining is not None else "?"

        styles.console.print(styles.format_idea_rich(idea))
        styles.console.print()

        choice = click.prompt(
            "  Keep (add a note), Archive, or Skip?",
            type=click.Choice(["k", "a", "s"], case_sensitive=False),
            default="s",
            show_choices=True,
            show_default=True,
        )

        if choice == "k":
            note_text = click.prompt("  Why is this worth keeping?")
            fast_path.add_idea_note(data_dir, idea.id, note_text)
            styles.print_success("Tended — decay clock reset")
            tended_count += 1
        elif choice == "a":
            fast_path.archive_idea(data_dir, idea.id)
            styles.console.print("[dim]  Archived.[/dim]")
            archived_count += 1
        else:
            styles.console.print("[dim]  Skipped.[/dim]")

        styles.console.print()

    # Summary
    parts = []
    if tended_count:
        parts.append(f"{tended_count} tended")
    if archived_count:
        parts.append(f"{archived_count} archived")
    if parts:
        styles.console.print(f"[dim]{', '.join(parts)}[/dim]")

    git_sync_after(data_dir, f"tend ideas ({tended_count} kept, {archived_count} archived)")


@ideas_group.command("rm")
@click.argument("idea_id")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation prompt")
def ideas_rm(idea_id: str, force: bool) -> None:
    """Permanently remove an idea.

    Use 'archive' instead to preserve the idea in search results.

    Example:

      marvin ideas rm ae23
    """
    if not ensure_setup():
        sys.exit(1)

    data_dir = get_data_dir()
    git_sync_before(data_dir)

    result = fast_path.find_idea_by_id(data_dir, idea_id)
    if result is None:
        styles.print_error(f"Idea '{idea_id}' not found.")
        sys.exit(1)

    _, _, idea = result

    if not force:
        click.confirm(
            f"Remove '[{idea.id[:4]}] {idea.thought}'?",
            abort=True,
        )

    removed = fast_path.remove_idea(data_dir, idea_id)
    if removed is None:
        styles.print_error(f"Idea '{idea_id}' not found.")
        sys.exit(1)

    styles.print_success(f"Removed: [{removed.id[:4]}] {removed.thought}")

    git_sync_after(data_dir, f"idea rm {idea_id}")


if __name__ == "__main__":
    main()
