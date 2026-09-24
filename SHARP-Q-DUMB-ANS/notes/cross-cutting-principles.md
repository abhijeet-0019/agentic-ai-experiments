# Cross-cutting principles

Things that kept recurring across every topic. More useful collected here than
scattered across six topic files. If a future decision feels hard, the answer is
usually one of these.

---

## 1. Prompting shifts probability. Code changes possibility.

The central architectural question in agentic engineering: what belongs in the
prompt, what belongs in code, and what needs a human?

A prompt makes an outcome more or less *likely*. Code makes an outcome
*possible or impossible*. **There is no such thing as a prompt with a 0% failure
rate.** So the decision rule is: *what happens in the tail case where the model
does the wrong thing anyway?* If the answer is "a slightly worse response,"
prompting is fine. If it's "money moved / data is gone / a contract was
breached," it cannot be a prompt, no matter how well written.

**Four tests to locate the boundary:**

1. **Can I write this as an assertion?** If the rule is a deterministic
   predicate (`if refund_amount > order_total: reject`), write it as one. The
   most common mistake in this field is a 40-line system prompt full of "rules"
   that are `if` statements in disguise. Conversely, if it resists formalization
   ("respond empathetically," "is this idiomatic code"), code *can't* express it
   — prompt territory by necessity.
2. **What's the worst case if this instruction is ignored?** Reversible and
   cheap -> prompt. Irreversible or expensive -> code. Irreversible *and*
   requiring judgment -> human.
3. **Does the model even have the information to decide?** Infra budget, rate
   limits, SLA, DB load — invisible to the model, so it cannot be trusted to
   reason about them regardless of prompt wording. You *can* put them in context,
   but per test 2 you still don't *rely* on it.
4. **Would I let a competent but occasionally careless junior engineer do this
   unsupervised?** If no, it needs a gate. Better calibrated than most formal
   rules because it taps delegation intuition you already have.

**Two different human-intervention mechanisms — conflating them is dangerous:**

- **Model-initiated escalation** — the model decides it's uncertain and asks.
  Useful, but it's prompt-level, so it inherits every prompt weakness.
  Critically: **the model is most dangerous exactly when it's confidently wrong
  — which is exactly when it won't ask.** Catches "I don't understand what you
  want." Does not catch "I'm about to do something irreversible while feeling
  great about it."
- **System-initiated gating** — code intercepts before execution and demands
  approval based on *what the action is*, not how the model feels. The model
  gets no vote.

**Rule: never let the model's own confidence trigger a safety-critical
checkpoint.** Gate on the action's classification. (Claude Code does both:
permission prompts fire because the *tool class* requires approval; "did you
mean X or Y?" is the other mechanism entirely.)

```
┌─ HUMAN ─────────────────────────────────────┐
│  novel situations, value judgments,         │
│  accountability for irreversible acts       │
│  ┌─ CODE ──────────────────────────────┐    │
│  │  invariants, validation, caps,      │    │
│  │  allow-lists — makes things         │    │
│  │  structurally impossible            │    │
│  │  ┌─ PROMPT ───────────────────┐     │    │
│  │  │  judgment, nuance, tone,    │     │    │
│  │  │  the 95% happy path         │     │    │
│  │  └─────────────────────────────┘     │    │
│  └──────────────────────────────────────┘    │
└──────────────────────────────────────────────┘
```

You don't pick one. **Each layer is designed assuming the layer inside it will
fail.**

**Anti-pattern in the other direction — over-coding.** A sprawling decision tree
in code to handle natural-language variation is fighting what the model is
genuinely good at. Code is bad at ambiguity and open-ended input. The boundary
isn't "code is safer, use more of it" — it's "use each layer for what it's good
at, and never rely on a layer for a guarantee it structurally cannot provide."

**Corollary that keeps paying off:** designing so that *the model being wrong
doesn't matter* always beats making the model less likely to be wrong. (See:
idempotency keys instead of "remember not to send twice.")

---

## 2. Irrelevant context is never neutral — it's a tax on discrimination

Appeared at five different layers of the stack, same root cause every time:
- System-prompt rule dilution (Topic 2) — rule #3 of 50 stops being followed in
  long conversations.
- Tool-list dilution (Topic 3) — a tool buried mid-list gets picked less
  reliably.
- Tool naming/description overlap (Topic 3) — similar descriptions produce
  similar representations, blurring selection.
- Agent scope (Topic 4) — one agent with every tool is jack of all trades,
  master of none.
- Memory (Topic 5) — an unpruned store dumped wholesale into every call.
- **Chunk size (Topic 6) — in embedding space, not attention space.** A chunk
  spanning three topics gets mean-pooled into one vector at the centroid of all
  three, strongly similar to none of them.

Root cause in context: attention is a **fixed budget** (softmax sums to 1), so
anything irrelevant competes for it. Root cause in embeddings: **pooling
averages**. The general form covers both — **any time you compress multiple
signals into one fixed-size representation, you destroy discrimination between
them.**

**Standing instinct: before adding a rule / tool / responsibility / memory to an
LLM's context, ask whether it's relevant to *this specific call*.** Fewer,
clearer, non-overlapping beats many, similar, diluted — every single time.

---

## 3. Prompts are influence, not enforcement

Stated separately from #1 because it's the specific form the lesson takes when
you're tempted to solve a problem by adding another sentence to the system
prompt. Recurred at least five times: grounding instructions, refusal clauses,
negative instructions, conflict-resolution-on-memory, "don't retry more than
twice."

If the failure is expensive, the fix is never a better sentence.

---

## 4. The model is stateless — at every level

- **API level** (Topic 1): no server-side session. Continuity is the app
  resending the transcript.
- **Token level** (Topic 2): no hidden scratchpad between generated tokens. The
  *only* memory between generation steps is what's been written into the token
  sequence — which is why chain-of-thought works at all, and why a reflection
  step must *write* its critique before a revision can use it.

Whenever something needs to persist or influence a later step, ask: **has it
been written down somewhere the model can attend to?** If not, it doesn't exist.

---

## 5. Determinism is not trustworthiness

`temperature=0` buys reproducibility, not correctness, not groundedness, not
good judgment on dimensions the model was never asked to optimize for.

- A deterministic model can be confidently, consistently wrong (Topic 1).
- It will still answer from general knowledge instead of your document unless
  explicitly grounded (Topic 2).
- It still can't reason about your infra budget, because it can't see it
  (Topic 4).

Separate the axes: **variance** (sampling randomness — temperature fixes it) vs.
**wrongness** (hallucination/faulty reasoning — temperature does nothing).

---

## 6. Verification is easier than generation

Reflection/self-critique loops work not because "double-checking is nice" but
because of a real asymmetry: checking whether code compiles and passes tests is
far easier than writing flawless code blind; checking whether a plan violates a
stated rule is easier than generating a fully rule-respecting plan first try.

**Design instinct: wherever you can convert a generation problem into a
generate-then-verify loop, do it** — and prefer verifiers that are code (cheap,
deterministic, trustworthy) over verifiers that are another LLM call.

---

## 7. Capability risk is a property of the *set*, not of each tool

Recurred as: the refund tool's blast radius (Topic 1), splitting destructive
tools across sub-agents (Topic 4), memory poisoning persisting across sessions
(Topic 5), the confused deputy across two MCP servers (Topic 7).

**You cannot assess tool risk one tool at a time.** Each capability can be
individually reasonable while the *combination* creates something neither
enables alone. Sharpest form — the **lethal trifecta**:

```
   access to private data
 + exposure to untrusted content
 + ability to communicate externally
 ─────────────────────────────────
 = an exfiltration channel
```

Any two is survivable. All three in one agent is a leak path, and no prompt
prevents it. Structural fixes only: **split the capabilities across agents** so
no single one holds all three, or **gate the egress** with system-initiated
approval keyed on action class.

Practical habit: audit the capability set of an agent as a whole — including
every connected MCP server, jointly — not server by server or tool by tool.

---

## 8. Syntactic guarantees are cheap; semantic guarantees don't exist

Constrained decoding can hard-guarantee the *shape* of output (valid JSON,
schema-conformant tool arguments). Nothing can guarantee the *values* are
correct or safe.

The danger always lives in **the gap between model output and system execution**
— a schema-perfect `{"order_id": "ORD-4471", "amount": 5000}` on a $50 order is
valid JSON and a $5,000 mistake. Validate values at the boundary; never treat
"it parsed" as "it's correct."

**The mechanism cuts both ways (Topic 8 lab).** A syntactic guarantee encoding
the *wrong contract* becomes a syntactic **prison**. A tool schema advertised `q`
while the Python function took `query`, under `strict: true` — so the model was
structurally forbidden from sending the correct argument. It retried three times,
varying the only free parameter it had (the *value* of `q`), and cycled back to a
call it had already watched fail. Perfectly rational behaviour inside a box with
no exit. The same mechanism that makes an `enum` safe makes a typo unrecoverable.

---

## 9. In an agent loop, your error messages are prompts

An error string returned from a tool is not diagnostics for a human reading a log
later. It is **the literal prompt for the next model call.** Its job is not to
describe what went wrong — it is to make the correct next action obvious.

Decided four separate runs in the Topic 8 lab, in both directions:

```
Error: 'open_threads' does not exist. Available notes: ['open_threads.md']
   -> recovered on the very next turn

Error: open_threads does not exist.
   -> implies "wrong filename"; model guessed .txt when the file was .md,
      burned three iterations, never recovered
```

Same failure. The second omits what *does* exist, so the only available repair is
guessing. **Test every error string a tool can return:** *if this were the only
new information a competent agent received, would it now do the right thing?*

**The precondition, which matters more than the wording (and which I missed).**
Before improving an error message, check whether the model **can act on it at
all**. Some failures are unrecoverable regardless of phrasing, because the fix
lies outside the action space you handed the model — see the `strict: true`
prison in #8. A perfect error message would have changed nothing there.

So the order is: **(1) can the model express the fix? (2) does the message name
the fix?** Skipping (1) and polishing (2) is wasted work.

**Corollary that surprised me:** a good enough error message can make a tool
redundant. A `read_note` failure that lists the directory does exactly what
`search_notes` was built for — and the model correctly stopped calling
`search_notes` at all. (Scale-dependent: true at 1 file, false at 500.)

**Applies equally to success messages.** Returning the exact bytes written
(`"Appended to X: [timestamp] content"`) rather than a bare `"ok"` is what lets
the model see what it actually did — including that it just did it twice.

---

## 10. An abstraction doesn't remove a decision — it makes it for you

The real cost of a framework is not lock-in or performance. It is that
decisions you used to make on purpose become defaults you never learn exist.

Lab 01 wrote `except Exception: return f"Error executing..."` — an explicit
choice to convert exceptions into text the model can read. Lab 02 got the same
behaviour only because it was restored deliberately; LangGraph's `ToolNode`
re-raises anything that isn't a validation error, which would have turned a
blocked path-traversal into a crashed process.

Three more from the same port, each reversing something lab 01 had decided on
purpose:
- `strict` is **off** by default, so a schema `enum` degrades from a syntactic
  guarantee to a strong suggestion (see #8).
- Per-argument descriptions are **silently dropped** unless you write
  `Annotated[str, Field(description=...)]` — and descriptions are what drive
  tool selection.
- `InMemorySaver`, the checkpointer every tutorial uses, **dies with the
  process** — so the durability that justifies the abstraction isn't there.

Also watch for **the knob with the same name that isn't the same knob**: lab 01's
`MAX_ITERS` counted model calls; `recursion_limit` counts node executions, so
the equivalent value is `2N − 1`. Renamed *and* rescaled.

**Habit: when adopting an abstraction, list what you were deciding by hand, then
go find what the abstraction now decides for you.** Anything you cannot locate
is a default you have silently accepted.

**Corollary — visibility is the first thing taken and the last thing missed.**
Across the whole raw-loop lab, every single bug was found by reading the request
payload, and none by reading application code. In a framework, graph state is
easy to print and the payload is not — it is built below your code.
**Budget for payload visibility on day one**, whatever you build on.
