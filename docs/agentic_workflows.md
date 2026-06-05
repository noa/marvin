# Agentic Workflows

This guide shows how AI agents can use Marvin to solve complex task management questions that require multi-step reasoning. Each example demonstrates an **observe → reason → decide → act** loop where the agent queries data, interprets intermediate results, and adapts its plan based on what it finds.

Agents can interact with Marvin via the **CLI** (shell-based agents read [`AGENTS.md`](../AGENTS.md)), or the **MCP server** (`marvin-mcp`). For detailed setup, see the [Agent Getting Started Guides](agents/overview.md).

---

## 1. "I have 5 things due this week. What should I prioritize?"

The PI asks for help sorting their week. This requires inspecting deadlines, checking waiting-on dependencies, and reasoning about urgency.

### Agent Trace

```
Agent: Let me see what's due this week.

> marvin.list_tasks(week=True)

Agent: 5 tasks due this week:
       1. Submit NSF progress report (due Mon) — high priority
       2. Review Sarah's draft (due Wed) — @waiting(Sarah)
       3. Grade homework assignments (due Thu)
       4. Confirm NeurIPS hotel booking (due Fri) — #conference
       5. Send budget revision to program officer (due Fri)

       Item 2 is waiting on Sarah. Is it actually actionable?

> marvin.show_person("Sarah")

Agent: Sarah Chen — PhD student. Notes say she sent the draft
       yesterday. So this IS actionable now; I should bump it up.

       Let me also check if item 5 has budget context.

> marvin.search_tasks("budget")

Agent: Found 2 additional budget-related tasks. One says "waiting
       for updated numbers from grants office" — that task is still
       open and blocking item 5.

       Recommended priority order:
       1. Submit NSF progress report (due Mon — earliest deadline)
       2. Review Sarah's draft (she's waiting on your feedback)
       3. Grade homework (fixed deadline, straightforward)
       4. Confirm hotel booking (can be done quickly)
       5. Budget revision (blocked until grants office responds)

       I'll add a note to the budget task about the dependency.

> marvin.add_note_to_task("...", "Blocked by grants office numbers — deprioritized for this week")
```

**What makes this agentic:** The agent doesn't just sort by deadline. It checks whether waiting-on items are actually unblocked, discovers a hidden dependency via search, and revises priorities accordingly.

---

## 2. "Clean up my task list"

The PI's task list has accumulated stale items. The agent needs to identify what can be cleared and propose batch operations.

### Agent Trace

```
Agent: Let me assess the current state.

> marvin.get_brief()

Agent: Brief shows:
       - 3 overdue items (7, 14, and 21 days late)
       - 12 tasks due this week
       - 4 waiting-on items

       Let me look at the overdue items specifically.

> marvin.list_tasks(overdue=True)

Agent: Overdue tasks:
       1. "Submit travel reimbursement" — 21 days late
       2. "Follow up with collaborator re: data sharing" — 14 days late
       3. "Order new lab supplies" — 7 days late

       These fall into two categories: some are probably done
       (reimbursement was likely submitted), others still need doing.

       Before clearing, let me check if any have subtasks.

> marvin.show_subtasks("...")  # travel reimbursement task

Agent: No subtasks. The reimbursement is likely done.
       I'll propose a plan:

       Tasks to mark as done (likely completed):
       - Submit travel reimbursement (21 days past — if not done, re-add)

       Tasks to reschedule:
       - Follow up with collaborator (still needed, extend deadline)
       - Order lab supplies (still needed, extend deadline)

       Shall I proceed?

       [User confirms]

> marvin.mark_task_done("...")  # travel reimbursement
> marvin.edit_task("...", deadline="2026-06-15")  # collaborator follow-up
> marvin.edit_task("...", deadline="2026-06-10")  # lab supplies
```

**What makes this agentic:** The agent triages overdue items into "probably done" vs "still needed" rather than blindly clearing everything. It checks for subtasks before deciding, and proposes different actions for different categories.

---

## 3. "Set up tracking for the NeurIPS submission"

The PI wants to track all the steps for a conference submission. The agent needs to research deadlines, create a task hierarchy, and set up collaborator records.

### Agent Trace

```
Agent: Let me find the NeurIPS 2026 deadlines first.

> marvin.search_tasks("NeurIPS")

Agent: Found 1 existing task: "Start thinking about NeurIPS 2026 paper".
       No deadline set. Let me research the actual dates.

       [Agent uses web search or marvin research command]

> marvin.add_task("NeurIPS 2026 abstract deadline @deadline(2026-05-15) #conference #deadline")

> marvin.add_task("NeurIPS 2026 full paper deadline @deadline(2026-05-22) #conference #deadline")

Agent: Now let me create the preparation subtasks under the
       existing "Start thinking about NeurIPS" task.

> marvin.add_task("Write experiment section", parent_id="...")
> marvin.add_task("Run final ablation experiments @waiting(Wei)", parent_id="...")
> marvin.add_task("Draft introduction and related work", parent_id="...")
> marvin.add_task("Prepare supplementary materials", parent_id="...")

Agent: I should also make sure the collaborators are tracked.

> marvin.list_people()

Agent: Wei is already in the system. Let me add the new co-author.

> marvin.add_person("Maria Rodriguez", role="collaborator", affiliation="Stanford NLP", tags=["nlp", "neurips"])

Agent: Setup complete:
       - 2 conference deadline tasks (auto-clear when past-due)
       - 4 subtasks under the main NeurIPS task
       - Wei assigned as waiting-on for ablation experiments
       - Maria added as collaborator
```

**What makes this agentic:** The agent creates a full project structure — deadlines, subtasks, collaborator records — from a single high-level request. It checks for existing tasks and people before creating duplicates.

---

## 4. Cross-Tool: "Add a task to review QUASAR spending — the numbers looked off"

This workflow uses both **Marvin** (tasks) and **Smaug** (budgets) when both MCP servers are registered. The agent investigates the budget anomaly before creating a task.

### Agent Trace

```
Agent: Let me check what's actually happening with QUASAR spending
       before creating a generic task.

> smaug.audit_spending("QUASAR", months=1)

Agent: Audit found a discrepancy: Chen's salary was under-billed
       by 50% in March — $3,000 charged vs. $6,000 expected.
       This is a specific issue I can create an actionable task for.

       Let me check if Chen is in the Marvin collaborators list.

> marvin.show_person("Chen")

Agent: Found Wei Chen — postdoc. Let me create the task with
       specific details from the audit.

> marvin.add_task(
>   "Follow up on Chen salary discrepancy on QUASAR — March charge "
>   "was $3k vs expected $6k. Contact payroll re: cost transfer."
> )

> marvin.edit_task(task_id="...", waiting="Wei Chen", add_tags=["grant", "urgent"])

Agent: Task created with audit-specific details:
       - Description includes the exact dollar amounts
       - Tagged #grant #urgent
       - Waiting on Wei Chen
       - Will appear in tomorrow's briefing

       I also notice QUASAR's stop-work date is getting close.
       Should I add a separate task for that?

> smaug.stopwork_forecast("QUASAR")

Agent: Stop-work projected for August 2026 — 2 months away.
       Creating a tracking task.

> marvin.add_task(
>   "Review QUASAR budget runway — stop-work projected Aug 2026 "
>   "@deadline(2026-07-01) #grant"
> )

Agent: Done. Two tasks created:
       1. Immediate: salary discrepancy follow-up (waiting on Wei Chen)
       2. Strategic: budget review before projected stop-work
```

**What makes this agentic:** The agent doesn't create a vague "review spending" task. It queries Smaug for the actual anomaly, cross-references the person in Marvin, creates a precise task with dollar amounts, and proactively surfaces a related concern (stop-work date) that the PI didn't ask about.
