# Topic 2 — Prompting & Context Engineering

## Grounding an agent to a document — right instinct, wrong lever
For an HR-policy-only assistant, correctly identified that a bare "you are an HR
assistant, only answer HR questions" system prompt is insufficient — the model will
blend in its general pretrained knowledge of HR topics alongside (or instead of)
the actual policy document.

Correct fix identified: explicitly instruct "only use the provided document, cite/
support answers with it, don't use outside knowledge."

Misconception caught and corrected: reached for `temperature=0` as part of the
grounding fix. Temperature controls **sampling variance**, not **groundedness** —
a model at `temperature=0` will confidently and *consistently* answer from general
knowledge instead of the document if not explicitly told not to. Same
variance-vs-wrongness distinction from Topic 1, reapplied: determinism ≠ "sticks
to the source."

Added missing piece: an explicit **refusal clause** — "if the answer isn't in the
document, say you don't know; don't guess." Without it, a model told "only use
this document" will still often fill gaps with plausible general knowledge rather
than admit it doesn't know, because refusing feels like failing the user. Common,
fixable production bug. (Enforcing this properly — e.g. citation-checking against
the source — is a Topic 6/RAG-grounding problem, flagged forward.)

## Few-shot prompting — pattern-matching instinct confirmed, mechanism + risk added
Correct: showing examples works because the model pattern-matches the input-output
shape instead of relying on (ambiguous) natural-language description.

Added: this is "in-context learning" — no weight updates, the model conditions its
next-token distribution on the analogous pattern sitting in context. Examples beat
instructions specifically because instructions are inherently interpretable
multiple ways, while a concrete example leaves no ambiguity about the target shape.

Risk flagged: few-shot examples are subject to the same **recency/ordering
effects** as everything else in context — the *last* example shown has outsized
influence. Unbalanced example sets (e.g. 3 "approve" + 1 "reject," reject last)
can bias the model unintentionally. Order is a design choice, not arbitrary.

## Why does a system-prompt rule degrade in long conversations if it's always at position 0?
Good diagnostic puzzle: system prompts are re-sent at the very start of every call,
so their *absolute* position never moves. If "lost in the middle" only cared about
absolute position, a system-prompt rule should never degrade. So why does it?

Landed on this after some flailing (initially reached for "the system misses
checking the instructions," which isn't how attention works — there's no discrete
lookup step; every generation step is one continuous, weighted pass over the whole
context):

Two real mechanisms, both compatible with the rule staying at position 0:
1. **Distance decay despite fixed position** — positional encoding weakens
   attention *by distance*, not by absolute position. As the conversation grows,
   the gap between "rule at position 0" and "token being generated now" keeps
   growing, so the *effective* pull of that specific content erodes even though
   its slot in the sequence never changes.
2. **Fixed attention budget / dilution** — softmax must sum to 1. A rule that's 15
   tokens out of a 2,000-token system prompt is competing against an ever-growing
   pile of recent, locally-relevant content for the same finite budget. Not
   "overridden" by any one thing — outbid by accumulated volume.

**Practical fixes, cheapest first:**
1. Re-assert the critical rule again right before the final user turn (the
   "sandwich" pattern from Topic 1 — now with the mechanism for *why* it's
   necessary specifically in long conversations).
2. Shrink competing volume — summarize/window old turns instead of resending
   everything verbatim.
3. Cut total rule count — fewer, higher-priority rules survive better than many
   equally-weighted ones.
4. For anything safety-critical, stop trusting the prompt at all — enforce as a
   programmatic guardrail on the tool-call layer instead. Same lesson as the
   refund example in Topic 1: prompts are influence, not enforcement.

## Detour: building a real mental model of attention (requested explicitly)
Went deep into the mechanics behind "attention," since it's the thing that
actually explains lost-in-the-middle, attention sinks, and few-shot recency —
rather than treating those as memorized trivia.

**Token-level vs. chunk-level embeddings (resolved a real conflation):**
Two separate systems both called "embedding":
- *Inside the transformer*: every **token** gets its own vector from a lookup
  table baked into model weights — happens every call, no vector DB involved.
  Comparison inside the transformer (via attention) is always token-level.
- *RAG / vector database*: a separate embedding model turns a whole **chunk**
  (paragraph/doc section) into one vector for approximate-nearest-neighbor
  retrieval. Purely a "what text to paste into the prompt" decision, made
  entirely outside the transformer. Once pasted in, the LLM re-tokenizes it like
  any other text. (Full treatment deferred to Topic 6 — RAG.)

**Dot product → cosine similarity, rebuilt from scratch:**
`A·B = Σ(a_i × b_i)` (arithmetic) equals `|A||B|cos(θ)` (geometric) — same value.
cos(θ) = 1 at θ=0° (same direction, max similarity), 0 at θ=90° (perpendicular,
*no relationship*), -1 at θ=180° (opposite direction, *actively contrasting*).

Verified numerically: `(1,0)·(1,0)=1` (θ=0°), `(1,0)·(0,1)=0` (θ=90°),
`(1,0)·(-1,0)=-1` (θ=180°).

**One real stumble worth keeping**: initially inverted the mapping — said dot≈0
meant "closely related" and large-negative meant "unrelated." Self-corrected
immediately on being pointed back at the worked numeric example. Final, correct
statement: dot≈0 → orthogonal → **unrelated** (no consistent relationship at all);
large negative → **opposite** (actively anti-correlated meaning). Genuinely two
different relationships, not degrees of the same one — worth remembering that
distinction explicitly since it's easy to blur.

Bridge to why this works for embeddings at all: training pulls vectors of
words/tokens used in similar contexts toward similar directions (e.g. "king" and
"queen" toward overlapping directions; "king" and "banana" toward ~orthogonal).
Cosine/dot product becomes a computable proxy for "used the same way across
training data."

**Query / Key / Value, via a search-engine analogy:**
- Query = "what am I looking for" (the implicit question a token asks).
- Key = "what do I offer, and how would you find me" (a searchable index tag).
- Value = the actual content handed over if a match is found.

Mechanically, per token `i` attending over context `1..n`:
1. `Query_i = x_i · W_Q`; every `Key_j = x_j · W_K`, `Value_j = x_j · W_V`
   (`W_Q/W_K/W_V` are learned, fixed at inference).
2. `Score(i,j) = dot(Query_i, Key_j)` — the exact same operation just rebuilt
   above.
3. Softmax across all `j` for fixed `i` → a probability distribution that **must
   sum to 1**. This forced-budget fact is the mechanical root of both attention
   sinks and lost-in-the-middle.
4. New vector for token `i` = weighted sum of every `Value_j`, weighted by that
   softmax score.

One head = this whole process with one set of `W_Q/W_K/W_V`. Real models run many
heads in parallel (multi-head attention), each free to specialize (grammar
tracking, long-range reference, sink-catching, etc.), outputs combined at the end.
(Multi-head specialization itself not yet gone deep on — parked.)

**Attention sink — a training-dynamics fact, not a math inevitability:**
First guess conflated the sink with recency (nearby-token relevance from natural
local coherence in language) — that's real too, but it's a *different*
phenomenon and doesn't explain why the sink persists even as the sink token gets
arbitrarily far away.

Actual mechanism: softmax must hand out 100% of its weight even when nothing in
context is a genuine match for a given query. Rather than distributing that
leftover weight unpredictably (injecting noise), models learn during training to
route it to a **fixed, predictable, low-information target** — the very first
token, because it's always present at a stable position. The model learns a Key
for it that's a generic catch-all, and a Value that's been shaped to be nearly
neutral so it doesn't distort the resulting blend (like a resistor to ground).
Empirically documented (StreamingLLM / "attention sink" research), not derivable
purely from the attention formula itself.

**Clarifying question worth keeping**: is the sink the first token of the *whole*
context (system prompt start / `<BOS>`) or the *latest* token? Answer: **the very
first token of the entire context — absolute position 0, fixed forever** (often a
dedicated `<BOS>` token some architectures are trained with). Not the latest —
that's recency, the opposite end of the same U-shaped curve, privileged for a
totally different reason (low distance-penalty vs. learned structural role).

**Positional encoding — the piece that completes "lost in the middle":**
Raw Q/K dot product has no notion of *where* a token sits — pure content-vs-content
similarity. Positional encoding injects position:
- **RoPE** — rotates Query/Key vectors by an angle proportional to position;
  distant pairs end up rotated out of alignment, discounting their score by
  distance alone, independent of content.
- **ALiBi** — simpler: subtracts a distance-proportional penalty directly from
  the raw score before softmax.

**Full "lost in the middle" picture, three forces stacked:** a middle token is
(1) far from the generation point → positional decay discounts it, (2) competing
against an ever-growing pile of tokens for one fixed softmax budget → diluted,
(3) not the sink → gets none of that structural protection. Start is protected by
the sink, end is protected by recency/low distance-penalty, middle gets neither.

## Multi-head attention — corrected a task-routing misconception
Initial framing: different heads get "selected" based on the type of task (research
vs. grammar check) — i.e. task-conditional routing.

Corrected: **all heads run on every token, every single time, regardless of what
kind of text it is.** No detection-then-route step. (What was being described —
conditionally activated specialized sub-networks — is a real, different
architecture: Mixture-of-Experts. Not what multi-head attention is.)

Actual reason for multiple heads: one head produces exactly **one** softmax
distribution per token — one "story" about relevance. If token B is grammatically
linked to token A *and* topically linked to token C, a single head has to
compress both signals into one shared weighting. Multiple heads (`d_model` split
into `h` heads of `d_model/h`, each with its own `W_Q/W_K/W_V`) let several
independent relevance-stories run in parallel, computed simultaneously, then get
concatenated and merged via one more learned matrix `W_O` at the end.

## Prompt caching — landed on the right answer via self-correction
Reasoned through initial confusion ("new stuff always gets added, so nothing can
be skipped") to the correct insight unprompted: the *static* prefix (system
prompt, tool defs) doesn't need its internal computation redone every call.

Precise version confirmed: what's cached is specifically the **Key and Value**
vectors for every token in the static prefix, at every layer — not the Query
(recomputed fresh each call, since it represents "what the current generation
step is asking"). Valid because of **causal masking**: an early token's K/V, at
every layer, can only ever depend on itself and tokens before it, never on
anything appended later — so an identical prefix guarantees bit-for-bit identical
K/V, deterministically (not a heuristic/approximation).

Practical consequence: caching only helps on an **exact prefix match** — one
changed token anywhere in the cached block invalidates the cache from that point
forward. This is why stable content (system prompt, tool schemas, long reference
docs) belongs first, and volatile content (latest user message) belongs last —
same ordering principle as the earlier context-engineering discussion, now with a
cost/latency reason behind it too. Full numbers deferred to Topic 11.

## Follow-up: is Key/Value static per token, or does it depend on the prompt?
Excellent follow-up question that forced a precise (not hand-wavy) answer.

Two things were being conflated: **the projection matrices `W_K`/`W_V`** (static —
learned once, identical for every token/position/prompt, forever) vs. **what gets
fed into them** (not static at all — evolves layer by layer).

Layer-by-layer resolution:
- **Layer 1**: a token's input is just its raw embedding + position, so
  `Key_i = x_i · W_K` at this layer is purely a function of that token's own
  identity — no cross-token info yet.
- **Attention at layer 1** blends in Values from every token at-or-before position
  `i` (causal), producing an updated vector for token `i` that now carries
  borrowed context.
- **Layer 2** computes `Key_i^(2)` from that *already-blended* vector — so from
  layer 2 onward, Key/Value indirectly encode information about everything before
  token `i`, even though the matrix itself never looks at another token directly.

Gossip-chain analogy: at each layer every token "hears" a blended summary of
everyone before it and updates itself; the transformation rule at each step is
fixed and identical for everyone, but what's being transformed keeps accumulating
context deeper into the stack.

**Resolved**: Key/Value for a token are not static regardless of prompt — they
depend on that token plus everything at-or-before its position (transitively,
through layered mixing), and *never* on anything after. This is precisely why
prompt-cache validity holds: shared prefix -> identical "before" context for every
token in it -> identical K/V at every layer, regardless of what's appended later.

## Delimiters/structure around retrieved or tool content
Instinct ("clear structure helps attention establish relationships") was directionally
right but vague. Sharpened into two concrete reasons:
- **Trained convention, not generic attention math** — `system`/`user`/`assistant`
  roles are literal special tokens models are trained to treat as hard boundaries;
  XML-style tags (`<document>...</document>`) around retrieved content invoke the
  same kind of learned, specific pattern, not just "cleaner attention" in the
  abstract.
- **Prompt injection (the missed, most important production reason)** — untrusted
  retrieved text with no clear boundary and no explicit "treat this as data, not
  instructions" caveat can get followed as a legitimate directive if it happens to
  contain instruction-shaped text (planted maliciously or by coincidence). This is
  a security boundary, not just a readability one — ties forward to Topic 10.

## Positive vs. negative instructions — confirmed with vocabulary
Correctly reasoned (in rougher language) that "don't mention competitor products"
still puts the tokens "competitor"/"product" into context, and next-token
prediction has no built-in "check against a blacklist" step — it's all
probability shaping. Formalized as **priming/activation**: writing forbidden
tokens into the prompt to negate them still raises their salience/availability to
attention; negation is one small word suppressing an already-activated pattern,
weaker than a clear affirmative target. Real, documented LLM weakness — practical
upshot: prefer scoped positive allow-lists over long negative deny-lists (same
"fewer, higher-priority rules survive better" lesson as the system-prompt-dilution
fix earlier).

## Chain-of-thought — why does "think step by step" actually improve accuracy?
Initial answer (tokens get grouped/organized under named steps) was a true side
effect but not the actual mechanism. Landed on the real explanation by combining
two things already established:

1. **Fixed computation per token** — every generated token gets exactly one
   forward pass through a fixed number of layers, regardless of problem
   difficulty. A genuinely multi-step problem (multi-digit math, multi-hop logic)
   can exceed what one bounded pass can derive if forced straight to a final
   answer.
2. **Statelessness, at the token level** — no hidden scratchpad carries silently
   from one generated token to the next; the only thing a future token can attend
   to is what's actually been written into the sequence. Same principle as
   API-level statelessness (Topic 1), one level deeper.

Combined: writing out "step 1: ..." appends that result into context, so
generating "step 2" gets a **fresh, full-depth forward pass** that can attend back
to an already-computed, externalized fact — instead of one fixed-depth pass
trying to derive the whole answer invisibly. CoT = trading more total sequential
compute (spent across many tokens) for accuracy on hard problems, by using the
token stream as the only available form of working memory.

**Forward link flagged**: this exact idea — more emitted tokens buys more
effective compute — is the conceptual seed of "reasoning models" (Claude's
extended thinking, OpenAI's o-series). Not a different architecture, chain-of-
thought taken to an extreme via training. Parked for Topic 4 (agent architectures)
or its own detour.

## Status
**Topic 2 closed.** Covered: grounding/refusal clauses, few-shot mechanics,
why system-prompt rules degrade in long conversations, a full attention/Q-K-V/
softmax/positional-encoding/multi-head/prompt-caching deep dive, delimiters
(incl. prompt injection), positive vs. negative instructions, and chain-of-
thought. Moving to Topic 3: Tool/function calling.
