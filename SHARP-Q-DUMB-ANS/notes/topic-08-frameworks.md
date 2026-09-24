# Topic 8 — Frameworks (Part 1: the raw loop)

Built before answering build-vs-buy, deliberately: you cannot judge what an
abstraction buys you if you have never done the thing it abstracts. This file
covers what writing ~300 lines of raw agent loop taught. **The build-vs-buy
verdict is not in here** — that needs the LangGraph port (Part 2).

Lab: `lab/01-raw-agent-loop/agent.py`. Provider: OpenAI, `gpt-4o-mini`.

---

## Setup decisions that turned out to carry weight

**Responses API over Chat Completions — with the trap disarmed.** The Responses
API can hold conversation state server-side via `previous_response_id`, which
would have hidden the single thing the lab exists to show. Kept `input_items`
client-side and refused the feature. Statelessness stayed physical: the whole
array is rebuilt and re-sent every turn, and you watch it grow.

**Switched provider mid-build (Anthropic → OpenAI).** Unplanned, and it turned
into the most useful reference artifact of the session, because the BRIEF was
written in Anthropic vocabulary and every target had to be re-derived.

| Concept | Anthropic Messages | OpenAI Chat Completions | OpenAI Responses |
|---|---|---|---|
| "model wants a tool" | `stop_reason == "tool_use"` | `finish_reason == "tool_calls"` | an output item with `type == "function_call"` |
| the call | `tool_use` block, `.input` is a **dict** | `message.tool_calls[i]`, `.function.arguments` is a **JSON string** | `.arguments` is a **JSON string** |
| correlation key | `tool_use_id` | `tool_call_id` | `call_id` |
| returning a result | `tool_result` blocks, **all in one** user message | **one message per call**, `{"role": "tool", ...}` | one item per call, `{"type": "function_call_output", ...}` |
| tool schema shape | `{name, description, input_schema}` | `{"type":"function","function":{...}}` **nested** | `{"type":"function", name, parameters}` **flat** |
| signalling an error | **`is_error: true`** | *no equivalent* | *no equivalent* |

**The last row is the interesting one.** Anthropic has a protocol-level error
flag. OpenAI has nothing — you write the error text into `content` and that's
the entire mechanism. Which forces the question the Anthropic path lets you
skip: *what should an error string actually say?* That turned out to be the
dominant finding of the whole lab.

---

## Gap 1 — in an agent loop, an error message is the next turn's prompt

The thing I kept getting wrong, four separate times. An error string here is not
diagnostics for a human reading a log later. It is **the prompt for the next
model call**, and its job is not to describe what went wrong — it is to make the
correct next action obvious.

Two runs, same loop, same model, same tools:

```
run 1   Error: 'open_threads' does not exist. Available notes: ['open_threads.md']
        -> recovered on the very next turn. 3 iterations, correct answer.

run 4   Error executing search_notes: got an unexpected keyword argument 'q'
        -> never recovered. 3 iterations, no answer, 654 tokens billed for nothing.
```

One names the valid alternatives. The other names only what is wrong.

The earliest version of this was worse and cost a whole run: `read_note` returned
`"Error: open_threads does not exist."` — true, but it implies *this one file* is
missing from a directory of others, so the model rationally repaired the
filename, guessing `open_threads.txt`. The real file was `open_threads.md`. It
was **one character class from correct** and had no way to close the gap. Four
words of error message cost three iterations.

**Test for every error string a tool can return:** *if this were the only new
information a competent agent received, would it now do the right thing?*

### Gap 1a — the precondition I'd missed (run 4)

Run 4 armed a deliberate schema/signature mismatch: the schema advertised `q`,
the Python function took `query`. The model's three attempts:

```
iter 1   search_notes({"q": ""})
iter 2   search_notes({"q": "*"})
iter 3   search_notes({"q": ""})     <- identical to iteration 1
```

Not a progression — a **return to a call it had already watched fail**, with the
failure visible in its own context. Output tokens `15, 15, 15`: flat. It wasn't
working harder. It was doing the same thing.

**And it was right to.** The schema is the only thing the model can see, and the
schema says `q` — `required: ["q"]`, `additionalProperties: false`,
`strict: true`. The model is *structurally forbidden* from sending `query`. It is
being told "`q` is wrong" by a system that gives it no legal way to send anything
else. The only free variable it had was the *value* of `q`, and varying it is
exactly what it did. **Optimal behaviour under the constraints I gave it.**

> **Before improving an error message, check whether the model can act on it at
> all.** Some failures are unrecoverable regardless of wording, because the fix
> lies outside the action space you handed the model. A perfect error message
> would have changed nothing in run 4.

This is principle #8 (syntactic guarantees) running in reverse: `strict: true`
is a hard guarantee, and a hard guarantee encoding a *wrong contract* becomes a
**syntactic prison**. The same mechanism that makes an `enum` safe makes a typo
unrecoverable.

---

## Gap 2 — vagueness makes a tool invisible, not confusable

The BRIEF predicted "two tools with vague, overlapping descriptions → wrong tool
picked." Ran it: both `search_notes` and `read_note` described as *"look up the
info"*, prompt `"what's in the open threads note?"` with no lexical hint.

**`search_notes` was never called. In any run where it had to be chosen rather
than named.** Not once across four runs.

What happened instead: the model reached for `read_note` and **guessed the
filename**. Given a choice between calling a tool to discover an argument and
inventing the argument, it invented.

> Confusion requires two tools that *both plausibly* match. A vague tool doesn't
> become confusable — it loses every contest and goes dark.

**The uncomfortable corollary.** What rescued run 1 was the error string listing
available notes — i.e. a directory listing — which is *precisely what
`search_notes` returns*. The error message did the tool's job in one turn. The
model wasn't wrong to ignore the tool; given that error, the tool was redundant.

*Caveat that keeps this honest:* true at N=1 file. At 500 notes you cannot dump
the directory into an error string and search earns its place. **This conclusion
is scale-dependent** — don't over-generalise it.

Connects to principle #2 (dilution): overlapping descriptions blur selection.
The new part is the *direction* of the failure.

---

## Gap 3 — containment is not an allowlist (the ghost file)

The sharpest self-inflicted wound, and it was predicted and then walked into
anyway.

`append_open_thread(file_name, content)` took a free-form filename. Asked to
append to "the open threads note," the model sent `file_name="open_threads"` — no
extension, mirroring the user's phrasing. `open(path, "a")` **created a brand new
file**. The tool returned `"Appended to open_threads"`, truthfully, twice. The
agent reported complete success. The real `open_threads.md` was never touched.

```
sample_notes/
  open_threads.md      <- the actual note, UNTOUCHED
  open_threads         <- ghost file, created by the agent, reported as success
```

Silent, successful-looking, and wrong — the worst failure shape there is.

**What did not save it:** `validate_file_path()` passed. `sample_notes/open_threads`
*is* inside `sample_notes/`. **Containment enforces *where*, not *what*.**

### The misconception this corrected

Asked where the earlier hallucinated-timestamp write should have been stopped —
system prompt, JSON schema, dispatch, or tool body — my answer was *"It cannot be
stopped by JSON schema"*, then self-corrected to *"put it in the tool
description."*

Both wrong, and wrong in the same way. **Moving a rule from the system prompt to
the tool description is changing seats, not floors** — both are text the model
reads and may ignore. And the schema is the *only* layer that could have made
this structurally impossible:

```python
"file_name": {"type": "string", "enum": ["open_threads.md"]}   # + strict: true
```

With `strict: true` the model **cannot emit** anything else. Syntactic guarantee,
not a semantic hope.

**Same class of bug, two different correct layers** — decided entirely by what
the schema can express:

| Tool | Legit input space | Right layer |
|---|---|---|
| `append_open_thread` | one known target | **schema** (`enum`) |
| `read_note` | arbitrary filenames | **code** (`is_relative_to` containment) |

And the timestamp half: the model invented `2023-10-04` because I made the date a
tool *parameter*. **Never let a model supply a value your runtime can compute.**
Fixed by generating it in the tool body.

---

## Gap 4 — `call_id` proven, not asserted

I'd claimed name-matching was "less deterministic" than ID-matching. Wrong word:
in the case that matters it is **undefined**. Run 2 produced the case exactly:

```
[1] tool_call    id=call_JtXC7Jjs...  -> append_open_thread({"file_name":"open_threads",...})
[2] tool_call    id=call_Tx1CE5pa...  -> append_open_thread({"file_name":"open_threads",...})
[3] tool_result  id=call_JtXC7Jjs...  -> Appended to open_threads: [...] review lab 01 notes
[4] tool_result  id=call_Tx1CE5pa...  -> Appended to open_threads: [...] review lab 01 notes
```

Same tool name. Same arguments. Same result text. Same timestamp (both fired in
one turn, same second). Items `[3]` and `[4]` differ in **exactly one field**:
`call_id`. There is no other information to match on.

Two further mechanics made concrete:
- **Both calls, then both results** — not interleaved. That's the required shape.
- The correlation is a **protocol** requirement, not a comprehension aid. The API
  pairs them before the model is ever invoked.

---

## Gap 5 — the last hop is the unverified one

Run 3, `"read every note and give me a one-line summary of each"`. Every tool
call succeeded. Both files were read correctly. Both results sat in context.
The final answer:

```
1. open_threads.md      : A casual greeting reflecting on life's ups and downs.
2. open_threads         : A repetition of a casual greeting with a poetic touch...
3. review lab 01 notes  : Notes related to a review of the first lab session...
```

There are **two** files. Summary 2 describes the *other* file's content — the two
were swapped. Summary 3 is invented: the model took the *content* of file 2
(`review lab 01 notes`) and promoted it into a third note that does not exist.

> **The tool layer working perfectly does not make the answer correct.** The last
> hop — the turn with no tool call, where the model writes prose — is verified by
> nothing, and it is the only part the user sees.

"The agent completed successfully" is a near-worthless signal. This is the
grounding problem from Topic 6 relocated: not retrieval failure, *synthesis*
failure, with ground truth visible in context. Connects to principle #6 — the
place most needing a verifier is the step that has none.

---

## Gap 6 — three distinct token-growth shapes

`usage.input_tokens` per iteration, across runs:

```
run 1  127 -> 170 (+43)  -> 228 (+58)     sequential calls, real progress
run 3  131 -> 168 (+37)  -> 293 (+125)    parallel calls: 2 calls + 2 results in one step
run 4  164 -> 203 (+39)  -> 242 (+39)     flat delta, flat output -- pure no-progress
```

**The mechanism worth keeping:** every output token the model generates becomes
an input token on every subsequent turn, permanently. You pay for generated text
twice — once at output rates, then forever at input rates. A verbose tool result
is the worst case: re-billed every turn, carrying nothing actionable. (An early
error echoing a 95-character absolute path was exactly this.)

**Parallelism saves iterations, not tokens.** The `+125` step bought two results
in one round-trip; the token cost was identical to doing them sequentially.

**`+39, +39` with output pinned at `15, 15, 15` is a no-progress signature** you
can detect in code — rising input, flat output, zero new information.

**Prompt caching never engaged** in any run: `cached_tokens=0` throughout. Not a
bug — OpenAI needs a **≥1024-token prefix** before anything caches, and the
largest request in the lab was 301 tokens. The prefix *was* stable and correctly
ordered (tools first, growing transcript after); it was simply too small to
qualify.

---

## Gap 7 — an iteration cap is a bad no-progress detector

`MAX_ITERS` is not protection against *long* tasks. It is protection against
*stuck* tasks, and it cannot tell the two apart. Run 4 looped on an identical
failing call three times; the cap would have let it run to whatever number was
configured.

Two cheap detectors the transcript hands you for free:
1. **Hash `(tool_name, arguments)`.** A repeat after a prior error is a loop —
   break or escalate.
2. **Rising input with flat output.** Linear cost, zero progress.

**What actually stopped run 4 was a human.** The cap was wired as an interactive
prompt rather than a hard stop, a human saw the identical repeat and typed `n`.
At `MAX_ITERS = 20`, unattended, this burns twenty turns and you learn about it
from the bill. That HITL-on-cost-boundary pattern is Topic 10 arriving early, and
it worked — but it worked because a person was watching, which does not scale.

**Also mechanically important:** the model cannot see `MAX_ITERS`. It has no idea
it is on its last turn, so it cannot wrap up, summarise, or hand back. Both sides
are blind unless you tell it.

---

## Things the model did that I never designed

- **Found an undocumented "list all" affordance.** `search_notes({"query": ""})`
  — an empty string satisfies `required`, and `"" in anything` is `True`, so the
  substring matcher returned every file. `"minLength": 1` closes it. Useful here;
  the same boundary-probing behaviour is not always benign.
- **Scope creep.** Asked only to *search*, it searched, then read, then
  summarised. Helpful with read-only tools. It is the *same disposition* that
  wrote a hallucinated timestamp into a closed topic's notes when a write tool
  was in reach.

---

## Methodology note worth keeping

After fixing a run that failed, I re-ran with a *different, easier* prompt (one
containing the word "search", which handed the tool choice away for free) and
read the pass as confirmation. It confirmed nothing — the hard case had been
engineered out. **A passing test that avoids the hard case tells you nothing.**
Directly relevant to Topic 9.

---

## Open threads

- **Part 2: the LangGraph port.** The actual build-vs-buy verdict. Two questions
  to answer first-hand: (1) how fast can you see the exact payload being sent, in
  each version? (2) which of these ~300 lines did the framework genuinely
  *replace*, and which did it merely *rename*?
- **`ENFORCE_APPEND_TARGET = True` never run.** The schema-`enum` fix is written
  and switch-guarded but was never exercised against a live model. Worth one run
  to watch it become unemittable.
- **No-progress detector unimplemented.** Both signatures identified, neither
  coded.
- **Cache floor never crossed.** Every request was <1024 tokens, so prefix
  caching was never observed working. Needs a run with a genuinely long
  transcript.
- **`is_error` has no OpenAI equivalent** — parked question: does the Anthropic
  flag measurably change recovery behaviour versus the same text with no flag?

---
---

# Part 2 — the same agent in LangGraph

Lab: `lab/02-langgraph-port/`. Versions: `langgraph 1.2.12`,
`langchain-core 1.6.4`, `langchain-openai 1.6.5`.

**Controlled experiment, not a port.** Lab 02 imports lab 01's tool *bodies*
and its *config* (switches, descriptions, model) unchanged, and pins
`use_responses_api=True` so both labs hit the same OpenAI endpoint. Orchestration
is the only variable — anything that differs is attributable to the framework.

## What got built

| file | lines | what it is |
|---|---|---|
| `agent_graph.py` | 179 | hand-wired `StateGraph`, kept line-comparable to lab 01 |
| `agent_graph_hitl.py` | 137 | durable human-approval gate (SQLite checkpointer + `interrupt`) |
| `prebuilt_agent.py` | 28 | `create_react_agent` — the floor, for reference |
| *(lab 01 baseline)* | *301* | |

Deliberately **not** `create_react_agent` for the comparison file: a one-liner
would collapse the whole question into "the framework did everything" and teach
nothing about *what*.

## The line budget, by section

| section | lab 01 | lab 02 | |
|---|---|---|---|
| imports + config | 28 | 19 | −9 |
| tools | 38 | 18 *(wrappers; bodies imported)* | — |
| **tool schemas** | **74** | **0** *(derived)* | **−74** |
| **dispatch** | **23** | **0** *(`ToolNode`)* | **−23** |
| the loop | 57 | 45 *(nodes 21 + graph 8 + runner 16)* | −12 |
| **visibility** | **45** | **59** | **+14** |
| entrypoint | 26 | 28 | +2 |
| **total** | **291** | **169** | **−122** |

Adjusted for the 38 lines of tool bodies lab 02 imports rather than contains:
**291 → 207, about −29%.**

**Everything shrank except the one section that found every bug in lab 01.**

---

## In plain language: where LangGraph wins, and why

### 1. You stop writing the menu by hand

In lab 01 there were two separate documents that had to agree: the **menu** (74
lines of hand-written JSON Schema, which is all the model can see) and the
**kitchen** (the Python functions that actually run). Keeping two documents in
sync by hand is a job, and `ARM_BAD_ARGS` was what happens when they drift — the
menu said `q`, the kitchen only cooked `query`.

LangGraph prints the menu **from** the kitchen. `@tool` reads the function
signature and generates the schema.

So it isn't that the bug got easier to fix. **You cannot write that bug down
any more.** A menu listing a dish the kitchen can't cook is no longer
expressible. 74 lines → 0, and a failure mode deleted.

### 2. Its default error messages were better than mine

Lab 01's big lesson was error-message-as-prompt (principle #9). LangGraph's
built-in messages already follow it:

```
Error invoking tool 'search_notes' with kwargs {'q': ''} with error:
 query: Field required
 Please fix the error and try again.

Error: no_such_tool is not a valid tool, try one of [search_notes].
```

Both **name the fix.** Mine said only `got an unexpected keyword argument 'q'`
— which names the problem and not the repair, and cost 654 tokens for nothing.
Somebody else already learned this lesson and baked it into the default.

### 3. The loop becomes a shape instead of a `while`

Lab 01's `while True` with a `break` becomes topology — one edge from `tools`
back to `agent` *is* the cycle:

```
START -> agent -> tool calls? -> gate -> tools -+
                      |                          |
                     END        <----------------+
```

The payoff isn't fewer lines (the loop only went 57 → 45, because graph wiring
is net-new code). It's that **adding a step is adding a node**, not editing
control flow. Phase 2's approval gate slotted in as one node and two edges
without touching the loop. In lab 01 that would have been surgery inside the
`while`.

---

## In plain language: where the raw loop wins, and why

### 1. You can read the letter before you post it

This is the big one.

In lab 01, the thing about to be sent was **a variable in your hand**. `print()`
it and you saw exactly what the model would receive.

In LangGraph you hand your notes to a clerk, and the clerk writes and posts the
letter. You can read **your notes** (graph state) easily. You cannot read **the
letter** (the actual request payload) — it's assembled inside the model wrapper,
below your code. And *the letter is the thing that matters.*

> **State is not the payload.**

There is no supported hook that returns the serialised request body.
`on_chat_model_start` gives you message objects, not bytes. The only way to see
the truth was to instrument the HTTP client:

```python
http_client=httpx.Client(event_hooks={"request": [tap.on_request]})
```

That is reaching *below* LangGraph, below `langchain-openai`, to httpx. Which is
why visibility was the only section that grew: **45 → 59 lines.**

Why it matters, concretely — every lab 01 bug and how it was found:

| bug | found by reading |
|---|---|
| guessed `.txt`, file was `.md` | the tool result text |
| ghost file created | `arguments` — `"open_threads"`, no extension |
| two identical parallel appends | two `function_call` items in one response |
| invented a third note | the final prose vs. the tool results in context |
| the `strict` prison | `{"q": ""}` repeating verbatim |

**Not one was found by reading application code.** All five were found by
reading the payload. So "how fast can I see the payload" is the cycle time of
the entire debugging loop. When that goes from zero seconds to an afternoon of
plumbing, the bugs don't stop — **you just stop finding them.** That is how a
framework can make you feel faster while making you less correct.

### 2. Your safety net had one hole you didn't dig

Lab 01 had one net under the whole trapeze:

```python
except Exception as e:
    return f"Error executing {func_name}: {e}"
```

LangGraph's `ToolNode` has a net under *some* falls and bare floor under others:

```
validation error (bad args, unknown tool)  ->  ToolMessage, model recovers
exception from your tool BODY              ->  propagates, the run DIES
```

`_default_handle_tool_errors` returns the message for `ToolInvocationError` and
**re-raises everything else**. So `validate_file_path`'s `ValueError` — a
path-traversal attempt — goes from "model gets told no" to "process crashes."
Fixed with an explicit callable, which also puts the decision back on screen:

```python
ToolNode(TOOLS, handle_tool_errors=lambda e: f"Error executing tool: {e}")
```

**The general form, and the real cost of frameworks:**

> The framework didn't remove a decision. It made one for you — and you inherit
> it without ever learning a decision was available.

Same pattern three times over: `strict` is off by default (so a `Literal`
becomes a suggestion, not a guarantee); per-argument descriptions are silently
dropped unless you write `Annotated[..., Field(description=...)]`; body
exceptions kill the run. Three quiet defaults, each reversing something lab 01
had decided on purpose.

### 3. The knob with the same name isn't the same knob

Lab 01's `MAX_ITERS` counted **model calls**. LangGraph's `recursion_limit`
counts **super-steps** (node executions), and `agent → tools → agent` is three
super-steps for two model calls. So the cap is `2N − 1`, not `N`.

Renamed *and* rescaled. Copy the number across and your budget is wrong by ~2×.

---

## Phase 2 — and the thesis I had to abandon

**My prediction:** LangGraph pays for itself on durable state, resumable
human-in-the-loop, and multi-actor coordination.

**What phase 2 built, and it works:** a gate that fires on *action class* (a
write tool), never on model confidence — principle #1's system-initiated
gating. State persists to SQLite, the process exits, and a later process resumes
mid-graph. Verified statically: a *fresh* saver on the same file sees the
resumed state. Lab 01's `input()` died with its process.

**And the trap.** Every tutorial reaches for `InMemorySaver`, which **dies with
the process**. Follow the docs and you get interrupt/resume ergonomics with
*zero* durability — exactly as fragile as lab 01. Durability needs
`langgraph-checkpoint-sqlite`, a separate package. **The framework's headline
advantage is off by default.**

**Where the thesis broke.** Durable resume in lab 01 would be about **25
lines**: `json.dump(input_items)`, exit, reload, continue the `while`. A linear
loop has exactly *one* sensible place to save — the top. The checkpointer does
not beat one `json.dump`.

So the claim narrows, honestly:

> Durability and HITL are cheap to hand-roll **when the topology is linear.**
> A checkpointer earns its keep only when there are *many distinct resume
> points* — branches, parallel actors, fan-out/fan-in — where saving state stops
> being one sticky note and becomes a filing problem.

Which means the genuine case for LangGraph is the thing this lab never built:
**non-linear topology**, plus `get_state_history` (replay from an earlier
checkpoint), which is genuinely nasty by hand.

---

## The verdict

| dimension | winner | why |
|---|---|---|
| Boilerplate | **LangGraph** | 74 schema lines → 0, derived from signatures |
| A whole bug class | **LangGraph** | schema/signature drift is inexpressible |
| Default error messages | **LangGraph** | its defaults name the fix; mine didn't |
| Adding a step | **LangGraph** | a node, not surgery inside a `while` |
| **Seeing the payload** | **Raw loop** | state ≠ payload; needs an httpx hook |
| Exception safety | **Raw loop** | `ToolNode` re-raises body errors by default |
| Durable resume, linear | **tie** | ~25 lines either way |
| Non-linear topology, replay | **untested** | the only place LangGraph plausibly wins big |

### Decision rule

**A single-process agent with a linear loop does not need LangGraph.** Lab 01's
291 lines handled tool-calling fine, and tool-calling is not the hard part —
which is why the framework can't win there, only tie while hiding things.

Reach for it when **the shape stops being a line**: parallel actors, branches
that rejoin, many resume points, replay-from-checkpoint. Those are the costs
that grow combinatorially by hand.

And whichever you pick: **budget for payload visibility on day one.** It is the
first thing a framework takes and the last thing you notice is missing.

## Still open
- The one run worth spending on: `ENFORCE_APPEND_TARGET=True` + preset 2. The
  schema is verified correct (`enum`, `additionalProperties: false`,
  `strict: true`); what's unverified is that the model is thereby *unable* to
  emit `open_threads`. It's the only place you'd watch a syntactic guarantee
  hold.
- Non-linear topology — the untested case that the verdict actually turns on.
- `get_state_history` / time-travel replay.
- CrewAI and the Claude Agent SDK, both named in the syllabus, both untouched.

## Status
**Topic 8 closed.** Raw loop and LangGraph both built, measured, and compared on
evidence rather than opinion. Moving to Topic 9: Evaluation & observability —
which this lab twice demanded early (a passing test that dodges the hard case;
"the agent completed successfully" as a near-worthless signal).
