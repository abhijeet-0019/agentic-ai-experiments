# Topic 3 — Tool / function calling

## LLM recommends, agent executes — correct mental model, confirmed
Correctly separated: the LLM never executes anything itself — it's pure text/
structured-JSON in, text/structured-JSON out. The orchestrating code (Claude Code,
or any agent harness) is what actually calls the real API/tool. Good instinct to
self-correct "the LLM decides" to "the agent decides, based on what the LLM said."

## How the agent knows it's tool-call time — structured, not parsed from prose
Real question, correctly anticipated that this must be structured rather than
NLP-guessed from text. Confirmed and made precise:

- Model response comes back with a distinct `tool_use` content block —
  `{type: "tool_use", id, name, input}` — `input` is schema-valid JSON via the
  same constrained-decoding guarantee from Topic 1.
- `stop_reason` (same field introduced for truncation in Topic 1) carries a third
  value: `"tool_use"`, distinct from `"end_turn"` (model is done) and
  `"max_tokens"` (cut off). The agent checks this one field — no text parsing.
- Text commentary and a `tool_use` block can appear in the *same* response —
  `stop_reason` reflects why the turn ended, not "text vs. tool call" as
  mutually exclusive.

**Full loop:** agent sends context + tool defs -> model returns `tool_use` ->
agent executes the real tool -> agent builds a `tool_result` block tagged with
the matching `id` -> appends it and re-sends the whole conversation -> model
either calls another tool or finishes with `stop_reason: "end_turn"`. The `id`
correlation matters especially for **parallel tool calls** (a single response can
request several tools at once) — results must be matched back to the right
request, not just returned in arbitrary order. This loop is a formalized version
of the **ReAct** (Reason + Act) pattern — proper architecture treatment deferred
to Topic 4.

## Lost-in-the-middle applied to a long tool list — hypothesis mostly right, with a real correction
Good self-aware uncertainty flagged: is "start of tool list" the same as "start of
context"? Usually **no** — tool definitions are typically their own structured
block, rarely at literal token 0 (something else, e.g. system prompt, usually
precedes it). This matters because **the attention sink attaches specifically to
the true first token(s) of the whole sequence** — it doesn't restart at the
beginning of every sub-section. A tool at the start of the tool-list block doesn't
automatically inherit sink protection unless that block truly sits at position 0.

That said, edge tools (start and end of a long list) are still empirically more
reliably picked than middle ones, in real function-calling benchmarks — for two
separable reasons:
1. **Genuine local recency** — positional decay is by *relative* distance, so the
   last tools in the list get a real proximity advantage to the generation point,
   independent of the sink.
2. **Local training-data primacy bias** — the "important things come first in
   training data" mechanism (Topic 1) can show up within any structured list, not
   just at the true start of a document.

Also disentangled: clear delimiters/structure (Topic 2) help the model recognize
*what kind of content this is* ("this is a tool list") — a separate benefit from
*positional reliability of a specific middle entry*, which structure alone doesn't
fix.

**Practical mitigation flagged as a good decision (per user's own note — include
this explicitly):** when tool counts get large (dozens+), don't statically dump
the full list every call — do a retrieval step first (semantic search over tool
descriptions, RAG-like) to narrow to the handful actually relevant to the current
request, sidestepping the dilution problem entirely rather than fighting it with
ordering tricks.

## Tool call error handling
Correct core design, arrived at with good instincts: don't let the conversation
die on a tool error — feed the error back into context so the model can reason
over it and retry, bounded by a small retry count (2-3) as a safety net against
infinite/wasteful loops.

Two refinements added:
- **`is_error: true` is a real, dedicated field** on the `tool_result` block —
  same principle as `stop_reason`: an explicit structured signal, not something
  the model has to infer from error-shaped prose.
- **Not all failures deserve uniform retry.** A typo (`"Pariss"`) is genuinely
  fixable by the model re-reading its own input. A city that doesn't exist
  (`"Atlantis"`) is not — retrying identically after a bare "404" won't help, and
  the model may not even realize retrying is pointless unless the fed-back error
  carries real semantic detail (not just a status code). The bounded retry count
  is a necessary backstop, not a substitute for giving the model enough
  information to distinguish "my mistake, fix it" from "genuinely unavailable,
  tell the user."

## Tool naming/description quality — a real reliability lever
Good instinct: vague/overlapping tool names and descriptions cause the model to
mis-select between them. Sharpened the mechanism — not a separate embedding-
similarity lookup step, but the same in-context attention machinery: overlapping
wording produces overlapping contextual representations, making it harder for
attention to sharply discriminate "this one" from "that one," especially at
higher temperature.

Concrete practices that follow:
- **Specific, non-overlapping names** — `get_weather_by_city` over `weather`;
  distinguishing verbs made unmissable for related tools (`create_ticket` vs.
  `update_ticket`).
- **Descriptions should state when to use it AND when not to, pointing at the
  alternative** — e.g. "use this for current weather; do NOT use for historical
  data, use `get_historical_weather` instead." Nice callback to Topic 2's
  positive-vs-negative lesson: bare negation is weak (priming risk), but paired
  with a positive redirect it becomes a strong disambiguator.
- **Parameter descriptions are a separate lever from tool selection** — the right
  tool can still get wrong values without clear format/units/examples on each
  parameter (e.g. unspecified date format).
- **Concrete failure mode**: `send_email` vs. `send_notification` ambiguity
  doesn't just cause a wrong answer, it triggers the wrong real-world side effect
  — same danger/blast-radius framing as Topic 1's refund example.

**Pattern recognized across topics**: this is the third time "fewer, clearer,
non-overlapping beats many similar/diluted ones" has shown up — system-prompt
rules, and now tool definitions. Same root cause each time: finite attention has
to discriminate between competing signals, and ambiguity is the enemy at every
layer of the system.

## `tool_choice` — controlling how much freedom the model has
- `auto` (default) — model freely decides whether/which tool to call.
- `any`/`required` — must call some tool, model's choice which.
- **forced to a specific named tool** — used not just for obvious pipeline steps,
  but as a common trick to get strict structured output by defining a "tool"
  purely to lock the response schema, even when nothing is actually executed —
  the tightest form of the constrained-decoding guarantee from Topic 1.
- `none` — disable tool calling this turn even if tools are defined in context.

## Status
**Topic 3 closed.** Covered: tool_use/stop_reason mechanics, parallel-call
correlation, tool-list dilution + retrieval mitigation, error handling with
`is_error`, tool naming/description quality, and `tool_choice`. Moving to
Topic 4: Agent loops & architectures.
