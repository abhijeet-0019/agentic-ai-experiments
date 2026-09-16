# Agentic AI Engineering — Architecture & Design Questions
*Part 2 of 2 (companion to `agentic-ai-deep-reference.md`). These aren't glossary terms — they're decisions a real system design forces you to make, each with genuine trade-offs. For each: the question as it'd actually be asked, the considerations that matter, the "why" behind the reasoning, and a recommended default with the conditions under which you'd deviate from it.*

---

## Q1. Should you use RAG, fine-tuning, or a bigger context window for grounding a model in your domain/data?

**The considerations**: What are you actually trying to change — the model's *knowledge* (facts it can recall) or its *behavior* (style, format, task-specific skill)? How often does the underlying data change? How large is the corpus relative to a context window? What's your tolerance for latency/cost per request vs. up-front training cost?

**The reasoning**:
- **RAG** is the right default for knowledge that changes over time or is too large to fit in any context window, because it separates "what the model can do" (frozen) from "what's currently true" (live, retrieved) — see the deep reference, 6.1. It's also cheap to update (reindex a doc) and requires no retraining.
- **Fine-tuning** is the right tool for changing *behavior* — teaching a consistent output format, style, or a narrow skill the base model doesn't do well — not for injecting facts, because fine-tuning bakes patterns into weights at a point in time; it doesn't solve "the data changes weekly" any better than not fine-tuning does, and it's slower/costlier to iterate on than reindexing a RAG corpus.
- **Just use a bigger context window** (no retrieval, no fine-tuning — paste the whole corpus in) only when the corpus is genuinely small enough to fit with margin, and you're willing to pay the token cost on every single call. It sidesteps retrieval-miss failure modes entirely (6.8) but reintroduces lost-in-the-middle risk (1.8) at large sizes and doesn't scale cost-wise as the corpus grows.

**Recommended default**: RAG for anything knowledge-shaped and non-trivial in size or update frequency; fine-tuning layered on top (not instead of) RAG when you also need consistent behavior/format; full-context-stuffing only for small, mostly-static corpora where simplicity outweighs the cost.

**Follow-up worth having ready**: "Can you combine RAG and fine-tuning?" — Yes, and it's common: fine-tune for domain-specific tone/format/task behavior, RAG for the actual facts, so you're not asking fine-tuning to do a job (knowledge freshness) it's structurally bad at.

---

## Q2. Should this be a fixed workflow or an autonomous agent?

**The considerations**: Can you enumerate the steps and their order in advance? Does the right next step depend on information only available mid-task? What's your tolerance for unpredictable cost/latency and harder debugging?

**The reasoning**: This is the single most consequential architecture decision in the whole field (deep reference 4.2), because it trades predictability for flexibility. A workflow is testable close to the way traditional software is (same input → same code path every time); an agent's path can genuinely vary run to run, which means testing has to shift from "verify this exact sequence happened" to "verify the eventual outcome meets criteria across many runs" — a fundamentally different (and harder) testing posture.

**Recommended default**: Start with a workflow. Only introduce agentic (model-decides-the-path) behavior for the specific sub-parts of the task where the path truly can't be predetermined — you don't have to choose one pattern for an entire system; a workflow with one autonomous agentic step embedded in it is often the right answer, not "pure workflow" vs. "pure agent" as a binary choice.

**Why this default, not "agents are the exciting new thing so default to them"**: Every increment of autonomy you add is an increment of debugging surface, cost unpredictability, and testing difficulty you're choosing to take on — it should be justified by a concrete inability to predetermine the path, not by novelty or by "agents seem more impressive to build."

---

## Q3. Single agent or multi-agent — and if multi-agent, what topology?

**The considerations**: Are there genuinely distinct roles/skills involved that benefit from separate, narrower prompts? Does one phase produce a large volume of intermediate context (search results, tool output) that would pollute a later phase's context if kept in one continuous conversation? How much does inter-agent coordination overhead cost you in latency/complexity?

**The reasoning** (deep reference 4.6): The two legitimate reasons for multi-agent are prompt specialization (one agent doing two very different jobs tends to do both worse than two focused agents) and context isolation (one phase's noisy intermediate work shouldn't bloat another phase's context window). If neither applies to your task, multi-agent is very likely to be pure overhead — more LLM calls, more coordination code, more places for one agent's error to silently propagate into another's context uncorrected.

**Topology choice, if you do go multi-agent**:
- **Orchestrator–worker** (one manager decomposes and delegates, workers execute narrow sub-tasks, manager synthesizes) — the right default topology for most cases, because it keeps the hard "what needs to happen and in what order" reasoning in exactly one place, rather than distributing decision authority across N agents that then have to negotiate/coordinate among themselves.
- **Peer/debate topology** (agents check/critique each other as equals) — reach for this specifically when the goal is catching errors via disagreement (e.g., one agent drafts, another critiques) rather than decomposing a task into independent sub-parts — a different problem (quality assurance) than orchestration (task decomposition), and topology should match which problem you're actually solving.

**Recommended default**: Single agent until you can name the specific specialization or context-isolation need multi-agent would solve; orchestrator-worker as the default topology when you do need it.

---

## Q4. How do you design the memory architecture for a conversational agent that needs to persist across sessions?

**The considerations**: What needs to survive across sessions vs. just within one? How do you avoid unbounded cost growth as history accumulates? How do you avoid "the agent forgot something important" failures?

**The reasoning, layered** (deep reference Part 5): Short-term memory (raw conversation history within a session) is the cheapest, simplest layer, but bounded by context window and cost — it needs a compaction strategy (summarize older turns rather than either keeping everything or hard-dropping it) once it grows past a threshold, because summarization preserves *something* of old context while truncation loses it entirely. Long-term memory (facts that must survive across sessions) has to live *outside* the context window in a separate store, retrieved selectively (like RAG) rather than always-included, specifically because always-including it reproduces the exact cost blowup described in the deep reference's tricky-question Q8. On top of raw retrievable history (episodic memory), a periodically-distilled summary layer (semantic memory — "what do I generally know about this user/task") is worth building separately because re-deriving general facts from raw logs on every turn is both expensive and less reliable than maintaining a standing, periodically-updated profile.

**Recommended design**: (1) Raw session history with compaction once it nears a token threshold. (2) A long-term store (vector or structured DB) of durable facts, retrieved selectively per-turn based on relevance to the current message — never dumped in wholesale. (3) A periodic (not per-turn) background job that distills raw episodic history into an updated semantic profile, rather than computing it fresh on every request.

**Common mistake to flag**: Treating "add long-term memory" as "just always include the user's full history/profile in every prompt" — this is the single most common cause of both cost blowup and lost-in-the-middle-induced quality degradation in memory-enabled agents; memory needs retrieval discipline exactly like RAG does, because structurally it *is* RAG applied to a different corpus (facts about the user, rather than a document set).

---

## Q5. How do you design tool/permission boundaries for an agent that will take real-world actions?

**The considerations**: What's the worst realistic outcome if the agent calls a given tool wrong (bad arguments, wrong tool, successfully manipulated by injected content)? Which actions are reversible vs. not? Which need to happen instantly vs. can tolerate a review step?

**The reasoning**: This is the blast-radius framework (deep reference 4.8) applied concretely. You cannot drive the probability of a wrong or manipulated tool call to zero — that's a structural property of these systems (hallucination, 1.5; prompt injection, 2.4), not a bug you'll eventually eliminate through better prompting. Given that, the only lever fully in your control is consequence, so design should proceed action-by-action, not tool-by-tool as an afterthought:

- **Low blast radius** (read-only, reversible, internal-only — search, lookup, draft-without-sending): safe to let the agent execute fully autonomously.
- **Medium blast radius** (affects internal state but is reversible/correctable — updating a draft record, scheduling something that can be canceled): autonomous execution is often fine, but add logging/audit trail so a mistake is at least visible and traceable after the fact.
- **High blast radius** (irreversible, external-facing, involves money/PII/real communication with third parties — sending an email, executing a payment, deleting data): requires a human-in-the-loop approval gate (10.2) before execution, regardless of how reliable the model has looked in testing, because testing reliability doesn't change the *worst-case* consequence, only its *likelihood* — and likelihood alone isn't the right thing to be managing here.

**On tool scoping specifically**: prefer several narrow, specifically-scoped tools (`get_order_status(order_id)`) over one broad, powerful tool (`query_database(sql: str)`) even when the broad tool is more "flexible" — narrow scoping is a security decision as much as a usability one, because the broad tool's worst-case misuse is categorically larger than the narrow tool's, independent of how good the model's judgment usually is.

---

## Q6. How do you design an agent system so it fails safely instead of looping forever or silently misbehaving?

**The considerations**: What stops a tool-use loop that isn't converging? How do you detect "stuck" behavior vs. legitimately-long-but-progressing work? What's the fallback when the agent genuinely can't complete the task?

**The reasoning** (deep reference 3.2, 4.1, and tricky-Q5): Nothing about the basic tool-use loop guarantees forward progress — it continues exactly as long as the model keeps requesting another tool call, with no inherent circuit breaker. Because you can't reliably prevent the underlying cause (an ambiguous tool result, a reasoning error the model keeps "fixing" the same wrong way) at the model level, the fix has to be structural, in your application layer, not a prompting fix:

- **Hard iteration cap** — bounds worst-case cost and latency even in a total failure case; the cap should be a deliberate, tested number, not an afterthought default.
- **Repeated-identical-call detection** — if the same tool + same (or near-identical) arguments is about to fire again within a short recent window, break the loop rather than let it continue, and route to either a clear "unable to complete" response or human escalation.
- **A defined fallback path** — every agent loop should have an explicit answer to "what happens when the cap/detection triggers," not just "the loop stops" with no further handling; typically this means returning a clear, honest "I wasn't able to complete this" rather than a truncated or silently wrong answer, or escalating to a human with the partial trace attached.

**Why this matters architecturally, not just as a bug-fix**: An agent loop with no circuit breaker is a system with an unbounded worst case in both cost and (for high-blast-radius tools) real-world consequence — the circuit breaker isn't a nice-to-have reliability feature, it's what makes the system's worst case actually bounded and describable, which is a basic requirement for anything running in production with real budget or real-world tool access.

---

## Q7. How do you decide where human-in-the-loop checkpoints go in a multi-step agent pipeline?

**The considerations**: At which points does the cost of a mistake spike relative to the step before it? Where can a human meaningfully evaluate the agent's proposed action before it's executed (i.e., where is "review this before it happens" actually tractable for a human, not just theoretically possible)?

**The reasoning**: HITL (10.2) exists to manage consequence at the exact point where an automatic action would have real-world effect — so checkpoints belong immediately *before* high-blast-radius actions (Q5's high tier), not scattered arbitrarily through the pipeline. Placing a review checkpoint too early (e.g., reviewing an intermediate research summary before any real action is taken) adds friction without actually preventing the consequential mistake, which happens later; placing it too late (after the action already executed) isn't a checkpoint at all, it's an audit log. A well-designed pipeline typically has a plan-review checkpoint (for plan-and-execute architectures, 4.4 — reviewing the *plan* before any step executes, catching a wrong approach cheaply before any real-world action) plus per-action checkpoints immediately before any specific high-blast-radius tool call, rather than one single checkpoint trying to cover the whole pipeline.

**Recommended default**: Checkpoint at (a) plan approval, if using plan-and-execute, and (b) immediately before every individual high-blast-radius action — never rely on a single early-pipeline review to substitute for gating the actual consequential actions later.

---

## Q8. How would you design a production RAG pipeline end-to-end?

**The considerations**: This is really several sub-decisions bundled together — chunking strategy, retrieval strategy, freshness/reindexing, and grounding/verification — each with its own trade-off, and the "why" of each choice matters more than the specific tool picked.

**The reasoning, stage by stage**:
1. **Ingestion & chunking**: prefer structure-aware chunking (split along headings/sections) over fixed-token-count chunking where the source has real structure, because it respects the document's own logical units rather than cutting arbitrarily (deep reference 6.4); use overlap to reduce split-answer risk at chunk boundaries.
2. **Retrieval**: hybrid search (vector + keyword) by default, not vector-only, because vector search alone systematically underperforms on exact-match content (IDs, codes, names) that keyword search handles natively (6.6) — the two methods have complementary, non-overlapping failure modes, which is the actual justification for combining them rather than "hybrid sounds more thorough."
3. **Reranking**: add a reranking pass over the top-K candidates before final selection if retrieval quality on your eval set shows the *right* chunk is often retrieved but not ranked first — reranking specifically targets "found it, but not prioritized correctly," a different problem than "didn't find it at all" (which chunking/retrieval-strategy changes address instead).
4. **Freshness**: an explicit, triggered (not manual/ad hoc) reindexing pipeline tied to source-data changes, plus freshness metadata surfaced in answers — because staleness is invisible by default in a plain retrieval pipeline (6.8, tricky-Q4) and needs to be deliberately engineered, not assumed away.
5. **Grounding/answering**: explicit relevance-threshold check before generation (so "nothing relevant was retrieved" produces an honest "I don't know" rather than a confident guess, tricky-Q1) and citations in the final answer, so claims are independently verifiable rather than trusted on the model's word alone (6.9).
6. **Evaluation**: a golden set that specifically includes out-of-scope questions (no correct answer exists in the corpus) and near-duplicate-phrasing questions (tricky-Q3's scenario) as permanent eval cases, not just "questions we know the docs answer well," because those are exactly the categories a naive eval set misses.

**Why sequence the reasoning this way**: Each stage's design choice is justified by a specific, named failure mode it targets (6.8) — a good answer to this question demonstrates you're solving concrete, distinct problems at each stage, not just assembling a checklist of "things RAG systems usually have."

---

## Q9. How do you design observability for an agentic system, and what do you actually look at day to day?

**The considerations**: Agent failures can originate at any step in a multi-step loop — what needs to be captured to make root-causing tractable rather than speculative? What tells you something is wrong at a glance, versus what you dig into once you know where to look?

**The reasoning** (deep reference Part 9): The three pillars exist because none alone is sufficient — metrics tell you *that* something's wrong (an error-rate or cost spike) but not *why*; full traces tell you exactly what happened in one specific execution but are too granular to manually review at scale across all traffic; ongoing quality evals over real production traffic (not just a pre-launch eval) are what catch drift (9.6), which neither metrics nor traces directly reveal (a system can have zero errors and normal latency while quietly giving worse answers than it used to).

**Recommended day-to-day setup**: Dashboard-level metrics (latency, cost per request, tool-call error rate, loop-iteration count distribution, retrieval-hit rate if RAG is involved) as the first thing you look at — anomalies here tell you *where* to dig. Full tracing on-demand for any flagged/reported failure, not necessarily reviewed proactively for every request (too expensive at scale) but always captured and retained so it's available the moment a failure is reported (tricky-Q9's exact scenario — you cannot retroactively add tracing to a failure that already happened and wasn't logged). A rolling quality eval running continuously against a sample of real production traffic (not just your static golden set), specifically to catch drift that a one-time launch eval structurally cannot detect.

**Why "capture everything, review on-demand" rather than "review every trace"**: This mirrors the same reasoning as reranking in RAG (Q8) — cheap-and-broad (metrics) to know where to look, expensive-and-narrow (full trace review) only where you've already been told (by metrics or a user report) that something needs investigating.

---

## Q10. How do you control cost in a production agentic system without capping capability?

**The considerations**: Where does cost actually come from in an agent system (as opposed to a single-call feature), and which of those sources can be reduced without sacrificing the quality/capability that justifies having an agent at all?

**The reasoning** (deep reference Part 11): Agent cost has several distinct, separately-addressable sources, and conflating them leads to the wrong fix. **History resend cost** (every turn resends the full conversation due to statelessness, 1.4/5.1) is addressed by prompt caching (11.2) for the stable prefix, not by arbitrarily shortening history (which risks losing needed context) — caching reduces cost of resending without reducing what's actually retained. **Loop-length cost** (an N-step loop costs ~N times a single call, 11.4) is addressed by iteration caps and by only using full agentic loops where a workflow genuinely can't substitute (Q2) — this is a design-scope fix, not a cost-optimization afterthought. **Per-step model cost** is addressed by model routing (11.6) — using a cheaper/faster model for genuinely easier sub-steps (classification, simple extraction, routing) and reserving the expensive model for steps that actually require its full reasoning capability, which reduces spend without reducing quality specifically because you're not paying frontier prices for sub-tasks that never needed frontier capability in the first place.

**Recommended approach, in priority order**: (1) Confirm you're not using an agentic loop where a cheaper fixed workflow would do (the biggest lever, because it changes N in "cost scales with N steps" rather than optimizing each step). (2) Cache stable prompt content. (3) Route sub-tasks to the cheapest model that an eval confirms is adequate for that specific sub-task. (4) Cap iterations as a hard backstop regardless of the above.

**Why this ordering**: Fixing (1) can reduce cost by a large multiplicative factor (fewer, cheaper calls entirely); (2)–(4) are important but incremental optimizations on top of whatever architecture you've already chosen — architecture-level decisions dominate line-item optimizations, so they should be considered first, not last.

---

## Q11. How do you version and roll out changes to prompts/tools/models in a live agentic system without breaking things silently?

**The considerations**: A prompt change, a tool schema change, or a model version bump can each independently change agent behavior in ways that are hard to predict from reading the diff alone (because the actual behavior emerges from the model's interpretation, not from code you can statically analyze the way you would a traditional function change).

**The reasoning**: Because LLM behavior isn't statically analyzable the way traditional code is (you can't "read the diff" and know exactly how output will change, the way you could trace through a deterministic function), the safety net has to be empirical, not just a code review — this is precisely what the eval suite (9.1–9.2) is *for*: a prompt/tool/model change is evaluated against the golden set (plus, ideally, a sample of recent real production traffic) before rollout, treating eval-suite results as the actual gate, analogous to how traditional software treats a test suite as the gate for a code change. **Model version pinning** matters specifically because providers do sometimes update or deprecate model versions independent of any action on your part (deep reference 9.6, drift cause #1) — pin to a specific version rather than "always latest" for anything where behavior consistency matters, and treat a deliberate model version upgrade as its own reviewed, evaluated change, not something that happens to you silently.

**Recommended rollout pattern**: Run the eval suite (golden set + recent-traffic sample) against any prompt/tool/model change before it ships, the same way you'd require tests to pass before merging code; roll out behavior changes gradually (a canary/percentage rollout) where feasible, specifically because eval-suite coverage is never fully complete (9.2's representativeness limitation) and gradual rollout limits the blast radius of an eval gap you didn't anticipate; keep the previous prompt/tool/model version easily revertible, since "revert" is often the fastest real mitigation for an unexpected regression, faster than diagnosing and re-patching forward.

---

## Q12. How do you design a safe computer-use or browser-automation agent, given how much larger its action space is than a normal tool-calling agent?

**The considerations**: Unlike a hand-picked toolset (a curated, limited API surface you explicitly designed), a computer-use agent can, in principle, do anything the underlying UI allows — click any button, navigate anywhere, submit any form (deep reference 12.2). Blast radius (4.8) is structurally larger here, not just theoretically larger.

**The reasoning**: Because the action space itself is far less curated than a normal tool-calling agent's, the mitigations that work for narrow tool-calling agents (careful per-tool scoping, Q5) don't fully apply — you can't narrowly scope "everything a browser can do." The mitigation has to shift toward containing the *environment*, not just the *tool list*: sandboxing (10.4) — running the agent against an isolated browser/VM instance with no access to real credentials, real payment methods, or real user accounts by default — is the primary defense here, more so than in narrower agents, precisely because tool-level scoping is a weaker lever when the "tool" is effectively an entire computer's UI. Human approval gates (10.2) should trigger before any action that leaves the sandbox's blast radius (e.g., an action that would use real credentials, submit a real form with consequence, or complete a real purchase) rather than being applied per individual click, which would be both impractical and miss that the real risk is at specific consequential actions, not at the level of individual UI interactions.

**Recommended default**: Sandbox by default (isolated environment, no real credentials/payment access) for anything exploratory or where the full scope of actions can't be fully enumerated in advance; require explicit human approval before any action that would leave the sandbox and have a real-world, hard-to-reverse effect; prefer structured DOM-based interaction (12.3) over raw screenshot/pixel-based interaction wherever available, since it's a more reliable action-execution mechanism (correct element targeting) independent of the safety question, and more reliable execution also means fewer accidental wrong-clicks in the first place.

---

## Q13. How do you choose between building an agent yourself (raw loop / lightweight SDK) versus adopting a heavier framework (LangGraph, CrewAI, etc.)?

**The considerations**: Does your workflow's shape match what the framework assumes (linear-with-branches for LangGraph, role-based multi-agent for CrewAI)? How much do you need to see exactly what's being sent to the model on each call? What's your team's tolerance for depending on someone else's abstraction and its future breaking changes?

**The reasoning** (deep reference Part 8): Frameworks are genuinely valuable when your workflow's shape matches their core assumption — you get real plumbing (retry logic, streaming, memory abstractions, established patterns for the exact pattern you need) for free. They become a liability specifically when you need to do something the framework didn't anticipate, because you end up fighting the abstraction (working around its assumptions) rather than being helped by it — and debugging becomes harder because there are now framework-internal prompt templates and control-flow layers between your code and what actually reaches the model, which directly conflicts with the transparency you need when diagnosing context-engineering or hallucination issues (1.10, 1.5).

**Recommended default**: Start with a raw loop or a lightweight SDK (maximum transparency, own your own plumbing) until you've concretely hit a coordination-complexity wall a framework would genuinely solve — don't adopt a framework speculatively "because we'll probably need multi-agent eventually." This mirrors the same "least autonomy/complexity that solves the actual problem" principle used throughout this document (Q2's workflow-vs-agent reasoning, Q3's single-vs-multi-agent reasoning) applied one level up, to tooling choice itself: added abstraction is a cost you should be able to name a concrete justification for, not a default you reach for because it's available.

---

## Q14. How do you design the eval framework for an agentic system before you have significant production traffic to learn from?

**The considerations**: A golden dataset built purely from imagined test cases risks missing real usage patterns (deep reference 9.2's representativeness concern) — but you don't have production traffic yet at launch. How do you bootstrap a useful eval suite under that constraint, and how does it evolve once you do have traffic?

**The reasoning**: Pre-launch, build the golden set from the best available proxies for real usage — domain-expert-authored realistic queries, support-ticket history if a similar system existed before, and deliberately-included edge cases you can already reason about structurally (out-of-scope questions with no correct answer in your data, near-duplicate-phrasing pairs, adversarial/injection-style inputs) even without real traffic to draw them from, because these categories are predictable failure modes of the *architecture* itself (tricky-Q1, tricky-Q3, 2.4), not dependent on having observed real users hit them yet. Post-launch, the eval suite has to become a living artifact, not a one-time deliverable: continuously sample real production traffic (especially traffic the model handled poorly, per user feedback or low-confidence signals) into the golden set over time, specifically because this is the only way to catch the query-distribution-shift cause of drift (9.6) that a static pre-launch set structurally cannot represent.

**Recommended default**: Treat the pre-launch golden set as a deliberately incomplete first draft, weighted toward known structural failure modes rather than assumed to be representative of real usage; establish a standing process (not a one-off task) for folding real production traffic — especially flagged failures — into the eval set on an ongoing basis after launch.

---

## Q15. How do you design an agent system to be resumable/checkpointable for long-running, multi-step tasks?

**The considerations**: If a long-running agent task fails partway (a crash, a timeout, a transient tool failure), do you have to restart the entire task from scratch, or can you resume from where it left off? What has to be persisted to make resumption possible, and what happens to in-flight side effects from a partially-completed action?

**The reasoning**: This is the state-tracking discipline (deep reference 5.5) applied specifically to failure recovery. A system that only keeps state implicitly "in the conversation history" has no reliable way to resume — you'd have to re-derive "what step was I on, what's already been done" from an unstructured transcript, which is exactly the kind of information that can get lost or garbled during context compaction (5.3) if a summary happens to drop a "step 4 already completed" fact. Explicit, structured state (a persisted record of the plan, completed steps, and their results, separate from and alongside the raw conversation) is what makes resumption tractable — on failure, you reload the structured state, not the full conversation, and resume from the last completed step rather than restarting.

**Why idempotency (11.7) is a prerequisite for this, not a separate concern**: Resuming from "the last completed step" only works safely if you can be certain that step's side effects genuinely completed (and won't be duplicated by a resumed re-attempt of a step that actually already succeeded but wasn't marked as such due to the same crash). Checkpointing and idempotency solve adjacent halves of the same problem — checkpointing tells you where you were, idempotency makes it safe to be uncertain about the exact boundary and retry a step you're not 100% sure completed.

**Recommended default**: Persist structured task state (plan, completed-step markers, intermediate results) separately from conversational context, update it as each step genuinely completes (not optimistically before), and design every side-effecting step to be idempotent so an uncertain resume point is never a correctness risk.

---

*End. Together with `agentic-ai-deep-reference.md`, this pair is meant to stand alone — no dependency on the curriculum notes/syllabus in this project.*
