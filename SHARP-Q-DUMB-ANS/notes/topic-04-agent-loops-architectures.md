# Topic 4 — Agent loops & architectures

## What actually makes something "an agent"?
Started with "a decision based on an LLM response" and self-corrected — spotted
that this is too broad (a simple `if keyword in response: divert_to_db` is
clearly not an agent, even though it's "a decision based on an LLM response").
Good catch, landed on the real distinguishing question unprompted-ish after a
nudge:

**Not** "does the system have tools/memory/state" — **"who decides the control
flow at runtime: the developer's code, or the model itself?"**
- **Workflow** — the sequence of steps is predetermined in code; the LLM fills in
  *content* at fixed points in an already-fixed graph. True even for a
  sophisticated multi-call pipeline (classify -> lookup -> summarize -> respond)
  if the shape of that pipeline was decided by a developer, not the model.
- **Agent** — the sequence itself is not predetermined; the model decides, at
  each point, what happens next (which tool, whether to continue, when it's
  done), and the code just faithfully executes whatever the model decides and
  loops until a stopping signal. The path is emergent, not authored.

Same underlying loop mechanics from Topic 3 either way — the difference is
entirely about locus of control, not architecture.

## Agentic workflow / bounded autonomy — the real-world spectrum
Correctly pushed back on the workflow/agent split as too binary in practice —
reconstructed, essentially from scratch, what the field calls an **"agentic
workflow"** or **"bounded autonomy"**: code-level guardrails (max iterations,
budget caps, timeouts) wrapping model-level decision-making. This matches
Anthropic's own stated guidance: start with the simplest structure (plain
workflow) and add agentic freedom only where the task genuinely needs it —
unconstrained autonomy is a cost/reliability risk, not a free upgrade.

**Why the guardrails have to be external, stated precisely:** determinism
(`temperature=0`) is not the same as trustworthiness on dimensions the model was
never asked to optimize for. A model deciding "should I retry this tool call?" is
reasoning about task completion, not your infra budget, rate limits, or latency
SLA — those constraints must be enforced in code because the model has no
visibility into them and no incentive to self-regulate on them.

**Concrete stopping mechanisms (practical checklist):**
- Max iteration/turn cap — hard ceiling, full stop regardless of model intent.
- Cost/token budget — track cumulative spend, halt on breach.
- Wall-clock timeout — independent of iteration count (a single call can hang).
- Loop/no-progress detection — same tool, same/near-identical args, repeatedly,
  with no new information -> halt and escalate rather than trust self-correction.
- Human-in-the-loop checkpoints for high-blast-radius actions — pause for
  explicit approval before destructive/irreversible steps (callback to Topic 1's
  refund/danger framing).

**Failure modes of getting the cap wrong, both directions:**
- *Too late / never* — runaway cost, infinite retry loops.
- *Too early* (the one initially undersold in discussion, worth stating
  precisely): (1) a **confidently wrong "final answer"** — hitting the cap often
  forces one last "respond with what you have" prompt, and the model will comply
  with something that *sounds* complete even though it never finished — arguably
  worse than an explicit failure because it looks done; (2) **inconsistent
  real-world state** — if earlier steps already had side effects (partial DB
  writes, a batch of emails half-sent) before the cutoff, you're left with a
  half-completed real-world change and no natural rollback — cutting off early
  doesn't fail safely, it can leave the system worse off than not starting.

Per-tool calibration point (good, practical): iteration/retry budgets should be
set per-tool based on known/tested behavior (a single deterministic API call
needs no retries; a tool whose next input depends on its own prior output
legitimately needs several iterations) — same "not all errors deserve uniform
retry" lesson from Topic 3.

## Single-agent vs. multi-agent
Strong, self-generated answer via the Single Responsibility Principle analogy:
one agent loaded with every tool/responsibility ends up "jack of all trades,
master of none" because irrelevant tools/context for the current task still
pollute attention and dilute token weighting.

**Pattern recognized explicitly across the whole curriculum so far — worth
treating as a standing design instinct, not a one-off fact:** this is the
**fourth** appearance of the same root cause — system-prompt rule dilution
(Topic 2), tool-list dilution (Topic 3), tool naming/description overlap
(Topic 3), and now agent scope (Topic 4). Finite attention has to discriminate
between competing signals; anything irrelevant sitting in context is a tax on
that discrimination, never neutral. General instinct going forward: before
adding a rule/tool/responsibility to an LLM's context, ask if it's relevant to
*this specific call* — irrelevant-but-present things cost accuracy.

**Three more reasons for multi-agent, beyond context-focus:**
- **Parallelization** — independent sub-tasks run concurrently, cutting
  wall-clock latency vs. one agent working serially.
- **Right-sized compute per sub-task** — a planning/manager agent can run on an
  expensive capable model; a simple extraction sub-agent can run on a cheap fast
  one. Cost matched to difficulty instead of paying premium cost everywhere
  (Topic 11 preview).
- **Blast-radius containment** — if only one sub-agent holds a destructive tool
  (`delete_file`, `send_payment`), a hallucination/runaway loop in a *different*
  sub-agent structurally cannot reach that capability. An architecture-level
  safety boundary, not just a prompt-level guardrail.

**Honest tradeoff — multi-agent isn't free:** coordination overhead (someone
manages hand-offs and aggregates results), more total tokens spent (every agent
pays its own system-prompt overhead), and a new failure surface (information can
be lost or garbled at the hand-off boundary — itself a context-engineering
problem). Deliberate decomposition decision, not a default upgrade — same
"start simple, add complexity only as needed" instinct as the workflow/agent
spectrum.

## Named patterns: Plan-and-Execute vs. ReAct
**Plan-and-Execute** — generate the entire multi-step plan upfront (no tools
called yet), then execute it step by step, optionally replanning if reality
contradicts an assumption. A different point on the workflow-agent spectrum than
ReAct: a path exists ahead of time (workflow-like) but was generated dynamically
by the model, not hardcoded (agent-like), and can be revised.
- Cheaper/more predictable than ReAct — no full reasoning pass needed after every
  tool result, just execution against an already-decided plan.
- Enables a clean human-in-the-loop checkpoint: the plan can be shown for
  approval *before any tool runs*.
- More brittle to surprises — executing a stale plan after an assumption breaks
  produces wrong results unless replanning is explicitly built in. ReAct's
  per-step reassessment is more adaptive because it never commits more than one
  step ahead.

## Reflection / self-critique
Not a new mechanism — chain-of-thought applied one level up. Because the model
has no memory beyond what's written into tokens (Topic 2), it can't silently
"realize" an error and fix it invisibly — the critique itself must be generated
as text and appended to context before a revision step can use it. (Named
research pattern: "Reflexion" — self-generated verbal feedback as additional
context for a retry.)

**Why it actually helps — the generation-verification asymmetry, worth keeping
as a general principle**: it's often much easier for a model to *verify* whether
an answer satisfies a constraint than to *generate* a constraint-satisfying
answer directly in one shot (checking code compiles/passes tests vs. writing
flawless code blind; checking a plan doesn't violate a rule vs. generating a
fully rule-respecting plan first try). Reflection loops work because of this
asymmetry, not just because "double-checking is nice."

Real agents (including how Claude Code itself operates) blend plan / execute /
reflect / replan loosely rather than rigidly implementing one named pattern.

## Status
**Topic 4 closed.** Covered: workflow-vs-agent (locus of control), agentic
workflow/bounded autonomy, stopping-condition mechanisms and both failure
directions, single-vs-multi-agent tradeoffs, Plan-and-Execute vs. ReAct,
Reflection/self-critique. Moving to Topic 5: Memory & State.
Timestamp: 2023-10-04T00:00:00Z
