# Topic 1 — LLM as a component

## Gap: conflating the product (ChatGPT app) with the API (raw model)
Went in believing the model itself holds session memory — "it remembers our chat,"
"it does some internal compression as the session goes on."

Reality: the model is **stateless**. Every API call is one self-contained request:
`[system prompt, msg_1, ..., msg_n] -> response`. There is no server-side thread
sitting inside Anthropic/OpenAI that the model quietly reads from between calls.

What actually creates the feeling of a continuous conversation is the **app layer**
in front of the model — on every new turn, it reconstructs (or truncates/summarizes)
the prior transcript and resends the whole thing as part of the next call. Building
your own agent means *you* own that decision — what to resend, what to drop, what to
summarize. That's not a platform default, it's an engineering choice (this is where
Topic 5 — Memory & State — actually lives).

**Confirmed understanding (good failure-mode example, self-generated):**
If you tell an agent early in a session "my name is Abhijeet, I want to become an AI
engineer," and later ask "what should I do to achieve my dream?" — the agent only
knows what "my dream" refers to if that earlier fact was explicitly re-included in
the second call's payload. It's not memory loss, it's a missing re-injection.

## Side-thread: "lost in the middle" (worth the detour, kept in full)
Real phenomenon, not just "context window overflow forces summarization." Content
placed in the *middle* of an otherwise-fitting context gets attended to less
reliably than content at the start or end. Three compounding causes:

1. **Training data bias** — important info in typical training data (article
   intros/conclusions, instructions-then-answer pairs) tends to sit at the edges,
   so the model's learned prior favors those positions.
2. **Attention sinks** — softmax attention must sum to 1 even when nothing in
   context is truly relevant to the next token. Models learn to dump that leftover
   attention mass onto the first few tokens as a default "safe" target — measurable,
   documented behavior, not content-driven.
3. **Recency via causal attention + positional encoding** — generation is
   autoregressive; the most recent tokens are the fewest "hops" away from the token
   being generated, and schemes like RoPE/ALiBi actively decay attention strength
   with distance, favoring nearby (= late) tokens.

```
attention pull
  ^
  |████                                         ████
  |██████                                     ██████
  |████████        (middle: no edge          ████████
  |██████████       bonus, has to survive   ██████████
  |██████████       purely on relevance)    ██████████
  +--------------------------------------------------> position
   start (sink)          middle                  end (recency)
```

Caveat: empirical average tendency (Liu et al., "Lost in the Middle"), not a hard
law — newer models are explicitly trained against it and it's less severe than it
used to be, but still cheap to hedge against.

**Practical mitigation:** don't bury a critical instruction/fact in the middle of a
long context blob. State it in the system prompt (start) *and* restate it again
right before the final user turn if the context is long — a "sandwich" pattern.

**Open question flagged, not yet answered:** does the same lost-in-the-middle effect
show up in tool-calling — e.g. does a tool defined in the middle of a long tool list
get picked less reliably? (Revisit under Topic 3 — Tool/function calling.)

## Temperature — mechanism, not just "flexibility"
Guessed "flexibility," which was directionally right but had no mechanism behind it.

Actual mechanism: next-token prediction produces a logit per vocabulary token;
temperature divides logits by `T` before softmax.
- `T < 1` → sharpens distribution, more deterministic/"safe."
- `T > 1` → flattens distribution, more diverse, more risk of a bad pick.
- `T = 0` → special-cased as greedy decoding (always highest-probability token).
  Not a true softmax division (undefined at 0).

Sibling knob: `top_p` (nucleus sampling) — truncates the candidate pool to the
smallest set whose cumulative probability exceeds `p`, rather than reshaping the
whole curve. Often used together with temperature.

Why agents default to `temperature=0`: tool calls / side-effecting actions need
consistency, and evals need reproducible output to diff against. Caveat: even at
`T=0` output isn't always bit-identical across runs (floating point / batching
non-determinism on the inference engine) — "deterministic" is "much more
consistent," not an absolute guarantee.

## Structured output — syntactic guarantee vs. semantic guarantee
Correct instinct: prompting alone ("please output JSON") is never a guarantee,
since the model is still just generating tokens.

Missing piece: **constrained/grammar-based decoding** is a real, separate
mechanism — at each generation step the engine masks out logits for any token that
would break the target schema, so only valid-shape continuations are even
sampleable. This is how OpenAI "Structured Outputs" and Anthropic's forced
tool-use schemas work. It is not "the model trying harder," it's the decoding
process itself being restricted.

Net: **syntactic validity is hard-guaranteed** via constrained decoding.
**Semantic correctness (are the values true/sensible) is never guaranteed** — pure
reasoning, can be confidently wrong. Carries forward directly into Topic 3
(tool calling).

## Max tokens vs. context window vs. streaming — three separate things, one conflation
Conflated all three into "cap on total tokens, cut off because it's streaming."

- **Context window** = total budget, input + output together (e.g. 200K for
  Claude).
- **`max_tokens`** = a parameter *you* set per request, capping *only* the output
  length. Doesn't touch input size. Real constraint:
  `input_tokens + max_tokens ≤ context_window`.
- **Streaming** = delivery mode only (tokens arrive incrementally vs. all at
  once). Orthogonal to truncation — a non-streaming call can get cut off just as
  easily as a streaming one.

Practical hook: check the `stop_reason` (Anthropic) / `finish_reason` (OpenAI)
field on the response — `end_turn` = finished naturally, `max_tokens` = got cut
off. A lot of people never check this and then get blindsided by a JSON parser
crashing on a truncated object.

## Danger vs. wrongness — the blast-radius framing
Question posed: if constrained decoding guarantees valid *shape* but not correct
*values*, what's a concrete way an agent produces valid-schema JSON that's still
wrong/dangerous?

Had to untangle two axes the user had merged:
- **Variance** (sampling randomness, controlled by temperature — goes away at
  `T=0`).
- **Wrongness** (hallucination/faulty reasoning — independent of temperature; a
  deterministic model can be consistently, confidently wrong).

Worked example: tool `refund(order_id, amount)`. Model emits
`{"order_id": "ORD-4471", "amount": 5000}` — perfectly valid JSON, matches schema,
types correct. But the real order was $50 and the amount was hallucinated. If the
system executes this directly against a payment API with no check, that's a real
$5,000 refund on a $50 order.

**Conclusion: danger is conditional, not proportional to "wrongness."** A wrong
value is dangerous only when both hold: (1) it feeds a tool call with a real-world
side effect (money/file/email/DB — not just displayed text), and (2) there's no
validation layer between "model produced this" and "system executed this." The
danger lives in the gap between model output and system execution, not in the
JSON itself. Directly foreshadows Topic 10 (guardrails/human-in-the-loop) and is
core to Topic 3 (tool calling) design.

## Status
**Topic 1 closed.** Skipped multimodal input / rate limits for now (lighter,
operational, brief-only when we need them) — deferred, not forgotten. Moving to
Topic 2: Prompting & Context Engineering.
