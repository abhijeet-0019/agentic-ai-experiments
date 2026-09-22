# Topic 6 — RAG & retrieval

## The pipeline, and the misconception it corrects
Initial walkthrough was directionally right (query -> vector DB -> chunks -> LLM)
but skipped the mechanics. Two corrections that matter:

**The query has to be embedded too, and the LLM never touches the database.**

| Step | What happens | Call type |
|---|---|---|
| 0 (offline) | Chunk -> embed -> store with metadata | Embedding model, once per chunk |
| 1 | Query -> embedded | Embedding model (**same model as step 0**) |
| 2 | Vector similarity search -> top-k | **No model** — pure math/DB |
| 3 | *(optional)* Rerank | Reranker model |
| 4 | Assemble prompt | **Pure code** |
| 5 | Generate | **One LLM call** |

So the simple case is **exactly one LLM call**. The LLM does not search, does not
query the DB, does not decide what to retrieve — it receives a prompt with the
chunks already pasted in. (The variant where the model *does* decide is
retrieval-as-a-tool — the `search_memory` pattern from Topic 5 — a different
architecture.)

- **Steps 0 and 1 must use the same embedding model.** Different models produce
  vectors in unrelated coordinate systems; comparing across them is noise.
  Swapping models = re-embedding the entire corpus. A migration, not a config
  change.
- **Missed: query rewriting.** In multi-turn chat the raw message is often *"and
  what about for enterprise?"* — embedding that verbatim retrieves garbage,
  because the standalone string carries none of the conversation's subject. A
  cheap LLM call rewrites it first. Statelessness again: the retriever sees only
  the string you hand it.

## "How do we stop the LLM from answering from its training knowledge?"
Excellent question, asked unprompted. Answer has three layers and the first is
"you can't."

**Why not, mechanically:** there is no switch and no architectural separation to
exploit. The model does not hold a "retrieved knowledge" store and a "training
knowledge" store that it toggles between. Retrieved chunks are *tokens in
context*; training knowledge is *baked into the weights processing those
tokens*. Every generated token is shaped by both, inseparably. So grounding
instructions bias a distribution — cross-cutting #1 in pure form: a probability
problem at the prompt layer can never be a guarantee.

**Layer 1 — prompt (shifts probability):** grounding instruction + refusal
clause; **span-level inline citations** (`[doc_47]` after every claim, not a
source list at the end). Citations are the highest-leverage prompt technique
because they change the generation task — emitting an ungrounded claim now also
requires fabricating a pointer.

**Layer 2 — code (actual enforcement, the real answer):**
- **Retrieval gating** — if all top-k scores are below threshold, **don't call
  the LLM at all**; return "I don't have that information." Kills the single
  most common hallucination scenario (nothing relevant retrieved, model answers
  anyway). Deterministic, cheap, high impact.
- **Post-hoc citation verification** — do the cited ids exist in what was
  actually retrieved this turn? Any uncited claims? Fail -> retry/flag.
  Detection must be *code*, never the model's self-report (cross-cutting #1:
  model-initiated escalation fails exactly when the model is confidently wrong).
- **Entailment checking** — cheap second call: `(chunk, claim)` -> "does this
  support that?" Verification-beats-generation (cross-cutting #6).

**Worked example.** Company has *no* enterprise-specific refund policy, only a
standard consumer one. Query retrieves the consumer chunk at 0.61. With weak
grounding the model emits: *"Enterprise customers receive a 90-day refund window
with prorated credits for unused license seats."* — a completely plausible
**industry-standard answer from training data**, in no document the company
owns. A support agent relays it; now there's a contractual dispute over terms
never offered. Gating alone catches it (0.61 < threshold -> refuse). The prompt
fix *might*. Only the code fix *reliably* does.

## Chunking
Got self-containment as the core property, and named **overlap** unprompted.
Overlap's cost was added: it mitigates *boundary* splits only, doesn't help when
the antecedent is paragraphs away, and creates near-duplicates that eat the
top-k budget (retrieving three 60%-identical chunks = effectively retrieving
one).

Operational definition offered ("a good chunk is one that gets retrieved when
relevant") is **recall** — only half. Second half: **once retrieved, is it
sufficient to answer?** A chunk can retrieve perfectly and be useless as a
fragment.

**Missed: chunk size as a real tension, with a mechanical reason.**
- Too small -> orphaned references, insufficient alone.
- Too large -> **one chunk collapses to exactly one vector.** A chunk spanning
  refunds + shipping + warranty has its embedding pulled to the centroid of all
  three, strongly similar to none. A refund query matches it *worse* than it
  would match a tight refund-only chunk.

**Worked example — the orphaned reference, two distinct failures at once.**
Naive fixed-size splitting produces chunk 37:
> *"...must be submitted in writing. In such cases, a full refund is issued
> within 30 days of the request, less any usage-based charges..."*

1. **It won't retrieve** — contains neither "enterprise" nor a topic statement;
   embeds near generic billing language. Query *"refund policy for enterprise
   customers"* matches a *consumer* chunk that literally says "Refund Policy"
   instead. Wrong answer, caused by chunking rather than gating.
2. **Even if retrieved, it's ungrounded** — "in such cases," *what* cases? The
   antecedent is in chunk 36. The model must guess, and will.

**Fix — contextual enrichment.** Prepend situating context *before embedding*:
> *"[Refund Policy v3 -> §4.2 Enterprise Subscriptions -> Cancellation and
> Refunds] ...must be submitted in writing..."*

Now it embeds near "enterprise"+"refund" *and* reads correctly standalone.
Generate headers structurally from the document outline, or with a cheap LLM
pass per chunk (Anthropic published this as "contextual retrieval").

Also: **structure-aware splitting** (split on headings; never split a table —
half a table with no header row is worthless) and **metadata** (`source`,
`page`, `section`, `doc_version`, `last_updated`) — Topic 5's provenance
instinct applied to documents. You cannot filter on what you didn't store.

## Where RAG failures actually happen
A conceptual muddle corrected first: **retrieval scoring and attention weighting
are different mechanisms at different stages.** Ranking happens in the vector DB
via cosine similarity with the LLM not running at all. Attention happens later,
at generation, over chunks *already selected*. A chunk that loses retrieval
never reaches attention; a chunk that wins retrieval can still be ignored by
attention. Conflating them means debugging the wrong stage.

Failure locations:
- **Query-side** — vocabulary mismatch ("refund policy" vs. "reimbursement
  terms"; "SSO" vs. "SAML"); **exact identifiers are where embeddings are
  worst** (*"what does error code E-4471 mean?"* is near-meaningless to an
  embedding model). Fix: **hybrid search** — run BM25/keyword *and* vector
  search, fuse the rankings. Keyword nails exact tokens, vector nails
  paraphrase. One of the highest-value upgrades to naive RAG.
- **Retrieval-side** — `k` too small (answer needs 8 chunks, you retrieved 5;
  the model answers from a partial picture confidently because **nothing in
  context says "there was more"** — a silent failure); stale index; no metadata
  filtering (retrieving from `policy_v2_DEPRECATED.pdf`); conflicting chunks
  retrieved with nothing to resolve the conflict, so the model picks by position.
- **Assembly-side** — chunk ordering (best chunk placed 3rd of 5 lands in the
  dead zone; fix: **highest-scored chunks at the edges**, worst in the middle —
  the U-curve as a concrete engineering decision); too many chunks stuffed in.

**Worked example — everything works, answer still wrong.** Policy changes from
30 to 14 days on Sept 1. Index last rebuilt Aug 15. Retrieval is flawless —
right section, high similarity, well-formed chunk. Model reasons impeccably and
cites correctly: *"Enterprise customers may request a full refund within 30
days. [policy_v3, §4.2]"* **Every component behaved correctly; the citation is
real; the answer is wrong.** No prompt engineering fixes this and no model
capability detects it — the model cannot know what it wasn't shown. Fix is
operational: index freshness SLAs, re-embed on change, surface `last_updated`.

**The framing insight:**
> **Most RAG failures are retrieval failures, not generation failures.**

The instinct when an answer is bad is to rewrite the prompt; usually the prompt
was fine and the right chunk was never in context. Consequence: **measure
retrieval separately** — track `recall@k` (was the correct chunk in the top-k at
all?). Without that number you cannot distinguish "the model hallucinated" from
"the model was never given the answer," and you'll tune the wrong component for
weeks. (Bridge into Topic 9.)

## Transformer embeddings vs. retrieval embeddings
The conceptual question of the topic — asked directly, and worth keeping.

| | **Inside the transformer** | **RAG / retrieval embedding** |
|---|---|---|
| Granularity | One vector **per token** | One vector **per chunk** |
| Produced by | Lookup table, then contextualized layer-by-layer | Separate embedding model: forward pass, then **pooled** |
| Lifetime | Ephemeral, recomputed every pass | Persistent, stored for months |
| Purpose | Internal representation for generation | A **search key** |
| Trained for | Next-token prediction | **Similarity** (contrastive) |

**Pooling** is the missing mechanism: hundreds of token vectors become one chunk
vector by averaging them (mean pooling) or taking a `[CLS]` vector. This makes
"large chunks dilute" mechanically literal — mean-pooling 2,000 tokens spanning
three topics *arithmetically averages* them; the vector lands between all three
and is strongly similar to none.

**Why a separate model rather than the LLM's internals:** the *training
objective* differs. Embedding models are trained **contrastively** — given
(question, correct passage, unrelated passage), push the question toward the
correct one and away from the wrong one. After millions of such updates, the
space is organized so that **cosine similarity means "relevant."** LLM internal
vectors were optimized to predict the next token and were never shaped for that.
This also explains the migration cost: two models = two unrelated coordinate
systems.

**Practical gotcha:** many embedding models are trained asymmetrically (short
queries vs. long passages) and require prefixes like `"query: "` / `"passage: "`.
Omit them and retrieval silently degrades — nothing errors.

## Reranking
First explanation failed — too much jargon before the intuition. (Working
agreement updated: **intuition before jargon**, always.) The version that landed:

**The library with index cards.** A million books, each reduced years ago to a
single index card summarizing it. You write your question on a card and compare
cards. Fast — a million comparisons is nothing. But:

> **The book's card was written before anyone knew what your question would be.**

So it had to be generic. You are comparing two *summaries*, never reading the
book. A card saying *"policies about refunds and trial periods"* looks nearly
identical to a question card saying *"refunds after trial periods"* — even if
the book says refunds are **not** available after the trial.

**The alternative:** hand a librarian the actual book *and* the question
together, and let them read the book with the question in mind. Far better
judgment, far slower — one whole book per question. Can't do it for a million
books; *can* do it for the 50 the cards shortlisted.

Hence: cards narrow a million to 50 (fast, rough); librarian reads those 50
properly (slow, accurate) and picks 5.

Names attached afterwards — "encoder" = the thing that turns text into numbers:
- **Bi-encoder** = two separate encodings, months apart, compared. ← index cards
- **Cross-encoder** = one encoding of both together. ← the librarian

**The sentence that ties it to everything else:**
> When question and document are encoded separately, **there is never a moment
> when they are in the same context window together** — so attention never gets
> a chance to relate them. Reranking exists to create that moment.

In a cross-encoder, "after" in the question can genuinely attend to "terminates
upon expiration" in the document. In card-comparison that link isn't hard, it's
structurally impossible — the two texts are never in one forward pass.

**Worked example — where cosine similarity reliably fails.**
Query: *"Can enterprise customers get a refund after the trial period ends?"*
- **Chunk A** — *"Enterprise customers are eligible for refunds. Trial periods
  last 30 days. Refund requests are processed within 14 days."* High similarity;
  every keyword present. **Never answers the question.**
- **Chunk B** — *"Refund eligibility terminates upon trial expiration;
  post-trial cancellations receive prorated credit only."* Lower similarity;
  doesn't repeat "enterprise." **Answers it directly — negatively.**

Pooled vectors are notoriously bad at negation and scoping ("eligibility
terminates" and "refunds are available" share nearly all content words, so they
land near each other). **A correct negative answer losing to positive-sounding
filler is one of the most common real RAG failures**, and reranking is the
standard fix.

## When RAG is the wrong tool
1. **Questions needing the whole corpus.** *"How many policy exceptions do we
   have?"* The model counts the exceptions in the 5 chunks it got and returns a
   confident wrong number, with nothing signalling the gap. Top-k structurally
   cannot count, total, or exhaustively summarize. Use precomputed aggregates or
   a map-reduce pass.
2. **Structured/relational questions.** *"Average refund amount for enterprise
   customers last quarter?"* is SQL. Embeddings are terrible at numbers, date
   ranges, exact comparison. Text-to-SQL, not semantic search.
3. **The corpus fits in context.** A 20-page policy? Put it all in the prompt.
   No chunking, index, staleness, or retrieval failures — and prompt caching
   makes repeats cheap. **RAG is a workaround for finite context**; without that
   constraint, don't build the workaround. As context windows grow this
   threshold keeps moving, and plenty of production RAG systems didn't need to
   exist.
4. **Data changing faster than indexing.** Inventory, prices, ticket status —
   any index is stale on arrival. Call the live API as a **tool**. Clean line:
   **RAG is for static-ish knowledge; tools are for live state.**
5. **Guaranteed completeness required.** Legal discovery, compliance — "find
   every mention." Top-k gives *most similar*, never *all*. Use exhaustive
   keyword search.

## Status
**Topic 6 closed.** Note: the "intuition before jargon" rule was added to
`CLAUDE.md` after the first reranking explanation didn't land — honest "I didn't
follow that" feedback was the most useful input of the topic.
