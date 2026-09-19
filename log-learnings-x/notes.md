# LangGraph Learning Project — Session Notes

Running notes for revision. Filled in as we resolve each topic — short and to the point,
not a transcript. Source design: `my_intial_design.md`.

## Roadmap
1. State schema & reducers
2. Node design (what a node may/may not do)
3. Edges & conditional routing
4. Human-in-the-loop / interrupts
5. Checkpointer & persistence
6. LLM call design & structured output
7. Termination semantics (approved vs. max-retries)
8. Directory structure & scaffold
9. Terminal implementation — key mechanics
10. LangGraph Studio deployment

---

## Quick revision — concepts worth re-checking

Not criticism, just a map of where clarification was actually needed while building this,
so you can re-read the linked topic if any of these still feel shaky.

1. **A reducer must never contain slow/LLM work, even "just sometimes."** Early instinct was
   to put the threshold-check-and-summarize logic inside the reducer itself. Fix: the reducer
   stays a dumb, fast, synchronous branch; the LLM call and the decision to trigger it both
   live in a separate node (`compact_reviews`). → Topic 1, "Golden rule."
2. **A node only ever returns a delta — never `END`, never a next-node name.** The original
   hand-written design had both `generate_post` and `human_review` deciding graph flow
   directly. Fix: routing is a fully separate function (a router), wired via
   `add_conditional_edges`. → Topic 2.
3. **A counter belongs to the node that performs the counted action.** `re_gen_count` was
   initially placed inside `human_review` rather than `generate_post`. → Topic 2,
   "Single-responsibility per node."
4. **Never gate a step on an outcome you haven't observed yet.** Skipping `human_review` once
   the cap was about to be hit would have silently removed the possibility of the human
   approving the final attempt. General principle: don't shortcut past a step just because
   *one* of its outcomes is now moot — check that *all* outcomes are moot first. → Topic 3.
5. **A router can only see `State` — nothing else.** This is why `human_decision` had to be
   reinstated after being dropped in Topic 1: a node's local variables are invisible to
   anything outside that node unless explicitly written into its returned delta. → Topic 3.
6. **`interrupt()` and `input()` solve different problems and aren't interchangeable** —
   the original pseudocode used both without a clear idea of which did what. → Topic 4.
7. **Persistence is a property of the checkpointer, not of `interrupt()` itself.** "Killing
   the process always destroys everything" is only true for `MemorySaver`; `SqliteSaver`
   survives exactly that. → Topics 4–5.
8. **On resume, LangGraph re-runs the whole interrupted node from the top** — it does not
   resume mid-function. Anything before an `interrupt()` call re-executes on every resume,
   which is why `interrupt()` should be the first meaningful line of a node. → Topic 9.
9. **A `State` field's declared type has zero effect on what an LLM actually returns.**
   `output: list[str]` in `State` and `PostThread(posts: list[str])` in `schemas.py` are two
   unrelated things kept in sync by hand — nothing wires them together automatically. → Topic 6.
10. **`TypedDict` produces no real class at runtime — `isinstance` can't check against it.**
    Exactly why `ReplaceReviews` had to be a `@dataclass` instead of another `TypedDict`. → Topic 9.
11. **A field with a custom reducer can't be safely seeded with a plain value unless the
    reducer itself accounts for that shape.** The sharpest real bug hit during testing —
    seeding `review_msg` with a plain `[]` produced `[[]]`, not `[]`, because the first
    invoke's input is run through the reducer exactly like any node's delta. First patched
    narrowly (wrap the seed in `ReplaceReviews`), then fixed properly at the root once Topic
    10 revealed the narrow fix didn't cover Studio's plain-JSON thread creation. → Topic 9.

---

## 1. State schema & reducers — RESOLVED

**Core concept:** a reducer is declared ONCE, at the state-schema level, via
`Annotated[type, reducer_fn]` on a single field — not written inside a node.
LangGraph auto-calls `reducer_fn(old_value, new_value)` whenever *any* node
returns an update for that key. Fields with no `Annotated[...]` just get
overwritten (the implicit default reducer).

**Golden rule:** a reducer must stay a small, fast, synchronous, pure
function. It must NEVER make an LLM call (or any I/O) itself — that kind of
slow/fallible work belongs in a node. If a field needs occasional "smart"
processing (e.g. LLM summarization), do it in a dedicated node, and have
that node hand the reducer an already-computed result. If the reducer needs
to behave differently depending on who's writing (e.g. "append" vs.
"replace everything"), have the node pass a distinguishable/tagged payload
shape, and branch on that shape inside the reducer — the branch itself is
still cheap/synchronous, only the decision of *which shape to send* required
the slow work, and that happened upstream in the node.
(Prior art: LangGraph's built-in message-history reducer uses exactly this
trick — a special `RemoveMessage` marker means "delete," anything else means
"append.")

**Finalized state schema:**
- `input_text: str` — set once, plain overwrite, no reducer.
- `output: list[str]` — ordered thread chunks (each meant to be ≤280 chars).
  Plain overwrite — a rejected attempt's output is never merged with the
  next attempt, always fully replaced. Getting the LLM to reliably *emit*
  this list shape (rather than one blob we manually chop) is a structured-
  output technique — see Topic 6.
- `re_gen_count: int` — plain overwrite; the node itself computes `old + 1`
  before returning, so no custom reducer is needed.
- `review_msg: list[...]` — custom reducer. Default behavior: append the
  new review comment. Exception: if the incoming payload is tagged as a
  summary/replace (from `compact_reviews`), discard the old list and start
  over with just the new condensed entry.
- Dropped `post_gen_status` (bool) and `post_review_status` (string) —
  neither has a real consumer: nothing in the graph reads `post_gen_status`
  to decide anything, and the approve/retry routing decision is made
  directly from the human's live input at `human_review`, not from a
  separately-maintained status flag.

**New node confirmed:** `compact_reviews`, sitting on the path between
`human_review`'s reject branch and `generate_post`. Reads `review_msg`,
checks its size; under threshold → passes the new raw comment through as a
plain append; over threshold → calls the LLM to condense the whole history
into one summary and returns it tagged for "replace." Not strictly required
at `re_gen_count`'s current cap of 5 (a 5-entry list will never blow up
context), but deliberately built anyway as a learning exercise / for reuse
in other projects with looser caps.

**Statelessness principle (why full context must be resent every call):**
LLM API calls are stateless — the model retains nothing between calls.
Anything it needs to "remember" (prior review feedback, its own last
output) must be explicitly re-included in the prompt on every single
invocation. `generate_post`'s prompt-builder must therefore assemble:
`input_text` + the full (possibly compacted) `review_msg` history +
`output` (the previous attempt) — every call, not just the latest review
entry. The graph's checkpointer persists *your* state between steps, but it
is still your code's job to decide what subset of that state gets
serialized into the actual LLM prompt each time — there is no ambient
model-side memory.

## 2. Node design — RESOLVED

**A node's only job: do one unit of work, return a partial state dict
(a "delta").** It never returns `END`, never returns another node's name,
never decides what runs next. It just reports what changed.

**The node does NOT commit anything itself.** LangGraph's own execution
engine is the single funnel that actually applies the change: it takes the
dict a node returns and, per key, calls that field's reducer (or does the
default overwrite) to produce the new canonical state. Same shape as
Redux's `dispatch → reducer → newState` or React's `setState` — you
describe the change, the framework applies it. This single-funnel design is
what makes checkpointing/interrupts/replay possible (Topics 4–5).

**Three distinct roles, easy to conflate:**
- **Node** (`add_node("name", fn)`) — registers a worker function under a
  name. Takes state in, returns a state-delta dict out.
- **Plain edge** (`add_edge("A", "B")`) — a fixed wire between node names,
  no function, no decision.
- **Router function** (passed directly into `add_conditional_edges("A",
  router_fn, {"label1": "B", "label2": END})`) — NOT registered via
  `add_node`, has no node identity. Called after A's delta has already been
  committed by the engine. Reads the fresh state, returns a plain label
  (string) — that's it. No state changes, no LLM calls, no "work."

**Single-responsibility per node:** a node should only touch state that is
naturally its own concern. Corrected during discussion: `re_gen_count`
increments inside `generate_post` (the node that performs the action being
counted), not inside `human_review` (whose job is only to capture the
human's decision on a post that already exists).

**Finalized node responsibilities:**
- `generate_post`: assemble prompt from `input_text` + full `review_msg`
  history + previous `output` → call LLM → return
  `{"output": [...], "re_gen_count": old + 1}`. Does not check the retry
  cap itself — that's a routing concern (Topic 3).
- `human_review`: capture the human's decision/comment → return
  `{"review_msg": ..., "human_decision": ...}`. Does not decide
  approved/rejected routing itself — a router function does that.
- `compact_reviews`: on the rejected path, checks `review_msg` size; under
  threshold, passes the new comment through as a plain append; over
  threshold, calls the LLM to condense and returns a "replace" tagged
  payload (see Topic 1).

## 3. Edges & conditional routing — RESOLVED

**Cap-check placement — the key trap avoided:** the retry-cap check must
happen ONLY after `human_review` has actually run, never before it. If you
gate `human_review` itself on "has the cap been reached," you silently
foreclose the *approve* outcome on the final allowed attempt — the human
never even gets to see it, and the system auto-declares failure even if
that last attempt was perfectly good. Human review always has two possible
outcomes (approve/reject); you can't know which one will happen in advance,
so you can't safely skip the step that finds out.

**Resolved flow:**
- `generate_post` runs → unconditional fixed edge → `human_review` runs
  EVERY time, including on the last allowed attempt.
- `human_review` displays the current attempt count / "this is your final
  attempt" to the human (pure display, reads existing `re_gen_count`, no
  new field needed for this) so the human decides with full information —
  this is what actually addresses the "don't waste the human's time /
  don't surprise them" concern, not skipping the step.
- `human_review` captures the human's Y/N decision (+ optional review text
  on reject) and returns a state delta. It does NOT decide routing itself.
- A single router function runs after `human_review`, reading state, with
  a three-way outcome:
  - `"approved"` → `END` (success)
  - `"rejected"` + `re_gen_count < cap` → `compact_reviews` → `generate_post`
    (retry)
  - `"rejected"` + `re_gen_count >= cap` → `END` (exhausted)
  One router doing a 3-way branch, not two separately chained conditional
  edges, since both facts (decision + count) must be considered together to
  pick the one next destination.
- Rejection feedback given on the final (cap-exhausted) attempt is NOT
  wasted even though it can't trigger another generation — it still gets
  included in the closing report/summary shown to the human (ties into
  Topic 7 — termination semantics).

**Field reinstated (with a real reason this time):** dropped
`post_review_status` in Topic 1 for having no consumer — now it does have
one: the router cannot see `human_review`'s local variables, only `State`,
so the Y/N decision must be written into state for the router to read it.
Reinstated as `human_decision: "approved" | "rejected"`, plain overwrite,
written by `human_review`, read only by the router immediately after.

## 4 & 5. Human-in-the-loop / interrupts + checkpointer & persistence — RESOLVED

**`input()` and `interrupt()` are not the same mechanism — different levels
entirely.**
- `input()` — plain Python blocking call. Freezes one line of code waiting
  on stdin. LangGraph's engine has no idea anything happened: nothing is
  checkpointed, there's no clean pause. If the process dies while blocked
  here, that node's progress is just gone.
- `interrupt(payload)` (called from inside a node) — the graph ENGINE
  itself cleanly stops the run, saves a full state snapshot via the
  checkpointer, and hands control back to whatever called
  `graph.invoke(...)`. The process is now free to do anything, including
  exit entirely.

**Correct architecture — these two calls live in different places:**
1. `human_review` (the node) calls `interrupt({...payload for the human...})`.
   This suspends the graph; the payload flows back out to the caller.
2. The OUTER driver/CLI script (plain Python, not a node) receives that
   payload, `print()`s it, and calls `input()` right there to collect the
   human's typed answer.
3. The driver then calls
   `graph.invoke(Command(resume=<answer>), config={"configurable": {"thread_id": "..."}})`.
4. Execution resumes inside `human_review`, exactly where `interrupt(...)`
   was called — that call now simply returns the `resume=` value, and the
   node continues normally from there.
`input()` never belongs inside a node. `interrupt()` never belongs in the
outer driver.

**Checkpointer — required for interrupts to mean anything, and the
persistence guarantee is entirely determined by WHICH checkpointer you
plug into `graph.compile(checkpointer=...)`, not by `interrupt()` itself:**
- `MemorySaver` — RAM only. Survives fine within one running process; gone
  the instant the process exits.
- `SqliteSaver` (or another real DB-backed saver) — writes every checkpoint
  to disk. Survives a killed process, a closed terminal, even a reboot. A
  fresh process invocation, given the same file and the same `thread_id`,
  reads the checkpoint back and resumes exactly where the graph paused.
  **Confirmed live during testing:** the process was SIGKILLed mid-review,
  and a brand-new invocation reproduced the exact same pending post purely
  from disk, with no re-generation.

**`thread_id`** — identifies one continuous run/session (NOT an OS thread).
Must be passed identically on the very first `invoke` and every subsequent
resume `invoke`, so the checkpointer knows "this is a continuation," not a
fresh run. Omit or change it → no link to the prior checkpoint, starts
fresh with no memory of what came before.

**Decision:** use `SqliteSaver` from the start for this project, even
though a single never-exited terminal session wouldn't strictly need
persistence — it's the realistic pattern, demonstrates the concept
properly, and is forward-compatible with LangGraph Studio deployment later
(which also relies on a checkpointer under the hood).

## 6. LLM call design & structured output — RESOLVED

**System message vs. human message — the dividing line:** system message =
stable role/rules/constraints for THIS task (persona, writing rules, the
280-char rule, objective) — unchanging across calls of the same purpose.
Human message = the variable, per-call data (`input_text`, full
`review_msg` history, previous `output`), templated in fresh every call.

**Each LLM-calling node gets its OWN system message, tailored to its own
task — not one shared global constant.** `generate_post`'s system message
frames a "write engaging posts" persona; `compact_reviews` needs a
different, smaller one framed around condensing feedback into key points.
Never reuse one node's system message for a different node's job.

**Structured output has NO automatic connection to the LangGraph State
schema.** Declaring `output: list[str]` in State only controls how a
node's returned dict gets merged — it does nothing to constrain what the
LLM produces. To actually get a reliable `list[str]` back: define a
Pydantic schema (e.g. `class PostThread(BaseModel): posts: list[str]`) and
call `llm.with_structured_output(PostThread)` inside the node — under the
hood this typically rides on the provider's native tool-calling to force a
parseable shape back. You wire this up by hand in every LLM-calling node;
nothing keeps schema and State type in sync automatically.

**Structured output guarantees SHAPE, not content quality.** Whether the
model smartly compresses a tiny leftover chunk into the previous post
(rather than creating an awkward near-empty final post) is entirely a
function of prompt instructions, not the schema. Division of labor:
structure = "you'll get back a valid, parseable list"; prompt = "here's the
actual judgment/reasoning I want you to apply when deciding the split."

**Messages sent to the LLM are a structured, role-tagged list**
(`SystemMessage`, `HumanMessage`, ...), not one flat concatenated blob —
this is the API contract you interact with, even though at the lowest
level inside the transformer everything eventually becomes one token
sequence (an implementation detail the API abstracts away). Role
separation matters because providers train models to weight `system`
differently from `human` turns — meaningfully more steerable than one blob.

**No internal agentic/tool-calling loop needed inside `generate_post`** —
one request in, one structured response out. The graph's own loop
(`generate_post` → `human_review` → back) is a separate, higher-level loop
driven by real human turns across separate `invoke`/resume calls, not by
the LLM calling itself repeatedly within one node execution.

**280-char enforcement — v1, then upgraded after a real failure:** soft
enforcement via the system prompt instruction, plus a Pydantic validator on
`PostThread.posts` as hard verification. Important nuance: the validator
only runs AFTER generation — it catches a violation, it does not prevent
one (tool-calling structured output constrains JSON shape, not
content-level rules like string length). **v2 (implemented after this
actually happened live in Studio — a real post came back at 285 chars and
crashed the run):** `generate_post` now catches `ValidationError`, appends
a `HumanMessage` describing exactly which rule was violated, and re-invokes
the LLM — capped at `MAX_SCHEMA_RETRIES = 2` extra attempts. If all
attempts still fail, the original error is re-raised rather than silently
falling back to truncation (that stays out of scope, per the original
decision). This is a self-contained retry loop *inside* `generate_post`,
not a graph-level regeneration — `re_gen_count` only increments once per
node call, exactly as before; internal schema-correction attempts are
invisible to the rest of the graph.

## 7. Termination semantics — RESOLVED

**Nodes never print. Only the outer driver script prints.** A node's only
output is a state delta (its data contract) — printing inside a node would
be invisible/pointless once this same graph runs under LangGraph Studio
later, since Studio visualizes state, not stdout. The driver reads the
final state (`human_decision`, `re_gen_count`) once `END` is reached, and
formats a human-facing message from it. State = source of truth; print =
a terminal-only view onto it.

**Distinguishing "paused again" from "actually finished," within one
continuous driver loop:** both look identical from the outside — either
way, `graph.invoke(...)` just returns control back to your code. Two ways
to tell them apart:
1. The returned dict carries a `"__interrupt__"` key when paused (holding
   the interrupt payload); its absence means nothing is pending.
2. `graph.get_state(config).next` — a tuple of node names still queued.
   Non-empty → paused, more work queued. Empty `()` → graph reached `END`.

Driver loop shape: `invoke` → check for a pending interrupt / non-empty
`.next` → if paused, print the interrupt payload, `input()`, resume; if
not, stop looping and print the final outcome from state.

**Confirmed live during testing:** the exhausted path correctly reviewed
all 5 attempts (never skipped one, labeled attempt 5 `"FINAL attempt"`),
never looped past the cap, and the final rejection's feedback still
appeared in the closing report even though it triggered no further
generation.

## 8. Directory structure & scaffold — RESOLVED

```
log-learnings-x/
├── my_intial_design.md
├── notes.md
├── langgraph.json          # for later Studio deployment
├── requirements.txt
├── .env                    # API key(s) — gitignored
├── .gitignore
├── checkpoints.db          # SqliteSaver file (gitignored, created at runtime)
├── sessions.json           # our own session index: thread_id/label/status (gitignored)
├── cli.py                  # outer driver: invoke/resume loop, input(), print()
│
└── src/
    └── post_agent/
        ├── __init__.py
        ├── state.py        # Topic 1: State TypedDict + review_msg reducer
        ├── schemas.py      # Topic 6: Pydantic models (PostThread etc.)
        ├── prompts.py      # Topic 6: one system-message template per LLM node
        ├── llm.py          # single get_llm() factory — model/provider/config
        │
        ├── nodes/
        │   ├── __init__.py
        │   ├── generate_post.py
        │   ├── human_review.py
        │   └── compact_reviews.py
        │
        ├── routers.py      # Topic 3: pure state-in, label-out functions
        └── graph.py        # add_node/add_edge/add_conditional_edges/compile
```

**Key architectural rule locked in by this structure:** everything under
`src/post_agent/` is interface-agnostic — it only ever produces/consumes
`State` and interrupt payloads, never touches stdin/stdout directly. All
terminal-specific logic (the interrupt/`.next` check, `input()`, `print()`)
lives ONLY in `cli.py`. This is what allows the exact same graph package to
later run unchanged under LangGraph Studio — Studio simply replaces
`cli.py` as the "driver," using its own UI for the interrupt payload and
resume input instead of a terminal.

**What `checkpoints.db` actually contains:** `SqliteSaver` manages its own
internal tables automatically (no schema you design) — rows are serialized
snapshots of `State` at each step, keyed by `thread_id` + step, plus
bookkeeping on which node to resume at. Its only consumer is the graph
engine itself on resume; it is not general app data storage.

**`llm.py` vs `graph.py`:** `llm.py` is a dependency (one `get_llm()`
factory for model/provider/config, imported by any node that needs to call
an LLM) — it never touches graph structure. `graph.py` is pure wiring
(nodes/edges/routers) — it never calls an LLM directly. No overlap.

**Addendum — session listing/resume UX (CLI-level, NOT a LangGraph feature):**
LangGraph's checkpointer only saves/loads ONE thread's execution state; it
has no built-in "list my past sessions" feature. Chosen approach: maintain
a small separate sessions index ourselves (`sessions.json` — `thread_id`,
a human-readable label from the first ~40 chars of `input_text`, and status
`in_progress`/`done`). `cli.py` writes an entry when a thread starts,
updates status when it ends. Kept deliberately separate from graph
checkpoint state — session bookkeeping is a different concern from
execution state.

Important distinction: resuming a *paused* (interrupted) thread is real
continued execution (`.next` non-empty). Reopening an already-`END`ed
thread has nothing left to execute — at most you'd read its final state
back read-only via `graph.get_state(config)`. Checkpoint rows are NOT
auto-deleted on `END` by default — they persist in the db file until
explicitly purged (`checkpointer.delete_thread(...)`).

## 9. Terminal implementation — key mechanics — RESOLVED

**`TypedDict` vs. `@dataclass` — why `ReplaceReviews` couldn't be a
`TypedDict` like `ReviewEntry`:** at runtime, a `ReviewEntry` instance is
just a plain `dict` — `type({"text": "x"})` is `dict`, full stop.
`TypedDict` is a pure type-checker fiction that vanishes at runtime;
`isinstance(x, ReviewEntry)` isn't even valid, since there's no real class
to check against. `ReplaceReviews`, via `@dataclass`, is a genuine class —
`isinstance(new, ReplaceReviews)` is a real, meaningful check. The
reducer's whole tagging trick requires something actually distinguishable
at runtime, which only a real class (not `TypedDict`) can provide.
`@dataclass` itself is just the idiomatic, boilerplate-free way to write a
small "holds one value" class (auto-generates `__init__`/`__repr__`/`__eq__`).

**`schemas.py` vs. `state.py` — different problems, not overlapping:**
`State` is durable, checkpointed, evolving data for the whole run.
`PostThread`/`ReviewSummary` are not storage — they're response contracts,
describing the exact shape needed back from one specific LLM call, alive
only for the few milliseconds between "the model responds" and "we extract
the field we need into `State`." Once `generate_post` does `result.posts`
and returns `{"output": result.posts}`, the `PostThread` object itself is
discarded — never part of `State`, never persisted. There are exactly two
schemas because there are exactly two places in the system that ask an LLM
for a specific structured shape back — not a general data-modeling file.

**Raw `.invoke()` vs. `.with_structured_output()`:**
- `get_llm().invoke(messages)` returns a plain `AIMessage` whose `.content`
  is free text — no guaranteed shape, you'd parse it yourself.
- `get_llm().with_structured_output(PostThread)` wraps the client: before
  sending, builds a tool/schema definition from the Pydantic model; after
  the response, parses the model's JSON straight into a validated
  `PostThread` object (running `check_length` in the process). That's why
  the code reads `result.posts` directly rather than parsing a string.

**Where prompt text vs. schema field descriptions actually land — three
separate parts of one request, never concatenated by us:**
`SystemMessage`/`HumanMessage` become the system message + messages array
(persona/rules + task data). `PostThread`'s `Field(description=...)` text
becomes part of a separate tool/schema definition (the `tools` parameter),
generated automatically by `with_structured_output` at wrap-time — never
merged into the message text itself.

**Why the `review_msg` reducer only fires for keys actually present in a
node's returned dict:** the engine's merge rule is — for every key present
in a node's returned dict, apply that field's reducer (or overwrite); any
key NOT present is left completely untouched. This is different from
"clearing" or "resetting" a field. This is why `compact_reviews`'s
under-threshold branch safely does `return {}` — no key means no reducer
call at all, `review_msg` just carries forward unchanged.

**Why an interrupted node re-runs entirely from the top on resume, rather
than resuming mid-function:** true mid-function suspension (like Python's
`yield`) only works because the frozen stack frame lives in the running
process's memory — it can't be serialized to a `.db` file and reconstructed
in a brand-new process started hours later. Since we deliberately designed
for surviving a fully killed process (Topics 4–5), the only thing that can
be durably saved is data — `State`, plus which node was interrupted — not
a paused stack frame. LangGraph instead re-runs the node deterministically
from the top, substituting the resume value at the exact `interrupt()`
call. (Same technique used by durable-execution engines like Temporal or
AWS Step Functions.) **Practical consequence:** anything before
`interrupt()` in a node re-executes on every resume — so `interrupt()`
should be the first meaningful line of a node. This is also a second,
independent reason (beyond single-responsibility) that `generate_post` and
`human_review` must stay separate nodes: if merged, the LLM call would sit
before `interrupt()` and would silently re-run — and re-bill — on every
single resume.

**A node's full return contract, consolidated:** a plain dict containing
only the keys that changed. Omitting a key = no change to that field. A
value is either plain (default overwrite) or a tagged shape the field's
reducer understands (`ReplaceReviews(...)` for `review_msg`). Never `END`,
never another node's name — that's still purely a router's job.

**`cli.py`'s loop, mechanically:**
- `graph.get_state(config)` is a pure read — runs no node, just reads the
  last checkpoint back off disk. Returns a `StateSnapshot`: `.values` (the
  actual `State` right now), `.next` (a tuple of node names still queued —
  empty `()` means `END` was reached), `.tasks` (pending-step detail,
  including `.tasks[0].interrupts[0].value` — the live interrupt payload).
- `if not snapshot.next:` — an empty tuple is falsy in Python, so this is
  `True` exactly when nothing is queued, i.e. the graph has actually
  finished.
- The loop shape: seed the very first `invoke()` only for a new session;
  every iteration after that (fresh or resumed, identical code path) just
  asks "where does this thread stand right now?" — if finished, report and
  stop; if not, show the pending interrupt, collect an answer, resume, and
  ask again. The loop never counts iterations itself — it's entirely driven
  by re-reading the graph's actual persisted status each time.

**The sharpest bug hit during testing — seeding a reducer-controlled
field:** seeding `cli.py`'s very first `invoke()` with a plain
`"review_msg": []` looked safe but wasn't: LangGraph applies the field's
reducer to the *initial invoke's input* exactly like any node's delta.
Since `review_msg_reducer`'s default behavior was "append the new value as
one item," passing `[]` produced `[[]]` — a list containing one empty
list, not an empty list — which is truthy and broke `_build_human_message`
(`TypeError: list indices must be integers or slices, not str`, from
trying `r["text"]` on a list `r`).

**First fix (narrow, later superseded):** seed with `ReplaceReviews(value=[])`
instead of a plain `[]`, reusing the "replace, don't append" tag built for
`compact_reviews`. This worked for `cli.py`, but only because `cli.py` is
Python code that can construct that object directly.

**Root-cause fix (Topic 10 forced this):** Studio lets you start a thread
by typing plain JSON, which has no way to express a Python-only tag like
`ReplaceReviews` — typing `"review_msg": []` there would hit the identical
bug again. The real fix belongs in the reducer itself: since a `ReviewEntry`
is always a `dict` and a `ReviewEntry` is never a `list`, any bare `list`
arriving at the reducer can only ever mean "set/seed the whole list
directly," never "append this as one entry" — so the reducer now special-
cases `isinstance(new, list)` the same way it special-cases `ReplaceReviews`.
This let `cli.py`'s seed go back to a plain, simple `[]`, and made Studio's
plain-JSON seeding safe too — confirmed by both. **Lesson, restated:** don't
patch a symptom at one call site if the actual defect is "the reducer
doesn't handle a shape it can legitimately receive" — fix it where every
caller benefits.

**Environment quirks worked through (specific to this machine, not
LangGraph):** the system default Python (3.8.10) is too old for this stack
(union-type syntax `X | Y` needs 3.10+; LangGraph/LangChain need 3.9+/3.10+)
— used `python3.13` instead. `python3.13 -m venv` couldn't bootstrap `pip`
on its own here (missing `ensurepip`) — worked around with
`python3.13 -m venv --without-pip venv` + manually running
`bootstrap.pypa.io/get-pip.py`. The org's pip config (`~/.pip/pip.conf`)
points at an internal Nexus mirror that doesn't carry `langgraph`; bypassed
it for one-off installs only via `PIP_CONFIG_FILE=/dev/null pip install
...` — a prefix env-var assignment that affects only that single command,
never modifies any config file, and never persists to later commands.

**End-to-end validated live (real LLM calls):** happy path (generate →
review → approve), reject/retry loop (feedback correctly incorporated
across regenerations), killed-process resume (SIGKILLed mid-review;
a brand-new process reproduced the exact same pending post from
`checkpoints.db` alone), and the exhausted path (all 5 attempts reviewed,
cap respected, final feedback preserved in the report).

## 10. LangGraph Studio deployment — RESOLVED

**`langgraph dev` is a free, fully local tool — not a cloud service.**
It's a small local API server (from the `langgraph-cli[inmem]` package)
running entirely on your machine, plus a browser-based Studio UI that
happens to be *served* from `smith.langchain.com` but talks directly from
your browser to `localhost` — no graph execution, state, or storage leaves
your machine. This is a completely separate, opt-in step from LangGraph
Platform (paid cloud deployment) — nothing here risked any billing.

**Zero changes needed to `generate_post`, `human_review`, `compact_reviews`,
or `routers.py`.** This is the direct payoff of Topic 8's interface-agnostic
design rule — Studio simply replaces `cli.py` as the driver, using its own
UI for the interrupt payload and resume input instead of a terminal.

**Two entry points into the same graph, with independent persistence —
not shared history:** `cli.py` explicitly constructs its own `SqliteSaver`
writing to `checkpoints.db`; `langgraph dev` wraps the graph with its own
separate internal persistence layer by default. Same underlying mechanism
(a LangGraph checkpoint store), two different physical locations that don't
know about each other — a thread started in one won't appear in the other's
thread list. `graph.py` now exports two things: `build_graph(checkpointer)`
(used by `cli.py`, our own explicit persistence) and a module-level
`graph = _build_wiring().compile()` with no checkpointer (used by Studio —
the platform supplies its own regardless of what we pass).

**Real gotcha hit and fixed: relative imports need a real installed
package, not a bare file path.** `langgraph.json` initially pointed at the
graph by file path (`"./src/post_agent/graph.py:graph"`); LangGraph's
loader `exec_module`s a file path directly, which gives Python no package
context, so `from .nodes.compact_reviews import ...` failed with
`ImportError: attempted relative import with no known parent package`.
Fix: added a minimal `pyproject.toml` (declaring `post_agent` as a package
under `src/`), ran `pip install -e .`, and pointed `langgraph.json` at the
graph by its **dotted module path** instead
(`"post_agent.graph:graph"`) — this makes the loader do a real `import`,
which does establish package context.

**The other real gotcha this surfaced — see Topic 9's updated entry:**
Studio's plain-JSON thread creation can't express the `ReplaceReviews` tag,
which forced the actual root-cause fix in `review_msg_reducer` itself
(handle a bare `list` directly) rather than the narrower `cli.py`-only
patch from before.

**Confirmed working end-to-end via the real API** (not just assumed from
docs): created a thread, seeded it with plain JSON `"review_msg": []`,
got back a clean `[]` (not `[[]]`) plus a correctly-shaped `__interrupt__`
payload identical in spirit to `cli.py`'s; resumed with `{"command":
{"resume": "y"}}`, got back `"human_decision": "approved"` and a clean
finish. `cli.py` re-verified working unchanged afterward.

## 11. Post-deployment fix — defending nodes against a partially-seeded state

**Real bug hit live in Studio (not hypothetical):** submitting through Studio's
own UI form sent only `{"input_text": "..."}` — none of `output`,
`re_gen_count`, `review_msg` were included. `generate_post` used bracket
access (`state["output"]`, `state["re_gen_count"]`) assuming `cli.py`'s
convention of always seeding a complete initial state — but Studio, a
caller we don't control, doesn't follow that convention. Result:
`KeyError: 'output'` crashed the run server-side — which also almost
certainly explains the earlier "redirects to Studio's home page" mystery:
Studio's UI likely falls back to a default view when a run errors like
this, rather than surfacing a clear inline message.

**The fix, and why it's narrowly scoped:** `generate_post` now uses
`state.get(key, default)` for `review_msg`, `output`, and `re_gen_count` —
the only node that needs this. Every other node (`human_review`,
`compact_reviews`, the router) only ever runs *after* `generate_post` has
already executed at least once via a fixed edge, and `generate_post`'s own
return always guarantees those keys exist by then, regardless of how
sparse the original caller's seed was. `input_text` deliberately stays
bracket access — if that's ever missing, it's a genuine caller error worth
a loud crash, not something to silently default away.

**Lesson, generalized from the Topic 9 seeding bug:** "always seed a
complete initial state" is a convention we can enforce in code we
control (`cli.py`), but not in every possible caller (Studio's UI, or any
future one). The durable fix belongs in the graph's true entry point,
defending against whatever a caller actually sends — not in every
caller's discipline.

**Operational gotcha, unrelated to the code:** `langgraph dev` spawns a
worker subprocess that can survive `pkill -f "langgraph dev"` and keep
holding port 2024 — check `ss -ltnp | grep 2024` after killing and
`kill -9` any PID still shown before restarting, or a fresh server may
silently fail to bind while an old one (with stale `.env` values, since
env vars are only read once at process start) keeps serving requests.

## Decisions log

**Tracing: LangSmith, enabled via env vars only, zero code changes.**
`langsmith` was already a transitive dependency (via `langchain-core`), so
no new install. `LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_API_KEY` +
`LANGCHAIN_PROJECT` (+ `LANGCHAIN_ENDPOINT`, required here since this
workspace isn't on the plain default endpoint) in `.env` — picked up
automatically since `llm.py` already calls `load_dotenv()`. LangGraph's
native LangSmith integration groups every `invoke`/resume sharing a
`thread_id` into one connected "thread" trace, with nested spans per node
and, inside the LLM-calling ones, the exact messages/tool-schema/response.
Confirmed working live.


**LLM provider: OpenAI** (`langchain-openai` + `ChatOpenAI`), using an
existing OPENAI_API_KEY. Considered using Claude via a Claude Code
subscription instead of an Anthropic API key — not viable cleanly: Claude
Code's subscription auth is scoped to the Claude Code CLI, not arbitrary
third-party apps. A workaround exists (pull a short-lived OAuth token via
`ant auth print-credentials --access-token` and set `ANTHROPIC_AUTH_TOKEN`)
but requires token-refresh handling — unnecessary complexity for this
project. All prior design decisions (state schema, nodes, routers,
interrupts, `with_structured_output`) are provider-agnostic — LangChain
abstracts the provider, so this choice only affects `llm.py` and
`requirements.txt`.
