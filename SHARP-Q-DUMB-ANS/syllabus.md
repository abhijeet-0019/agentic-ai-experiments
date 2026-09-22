# Agentic AI Engineering — Syllabus (living doc)

Order is a guide, not a fence — we jump around when a question pulls us somewhere else.
Check things off as we cover them meaningfully (not just "touched").

- [x] 1. LLM-as-a-component — what you're calling, its knobs/limits
- [x] 2. Prompting & context engineering
- [x] 3. Tool / function calling
- [x] 4. Agent loops & architectures (ReAct, plan-execute, single vs multi-agent)
- [x] 5. Memory & state (short-term context vs long-term recall)
- [x] 6. RAG & retrieval
- [x] 7. MCP & tool ecosystems
- [ ] 8. Frameworks (LangGraph, CrewAI, Claude Agent SDK, raw loops) — build vs buy
- [ ] 9. Evaluation & observability
- [ ] 10. Safety, guardrails, human-in-the-loop
- [ ] 11. Cost, latency, production concerns
- [ ] 12. Multi-modal / computer-use agents

## Notes index
- **[Cross-cutting principles](notes/cross-cutting-principles.md)** — the transferable stuff that keeps recurring: prompt-vs-code-vs-human boundary, context dilution, statelessness, determinism ≠ trustworthiness, verification asymmetry. Read this one first.
- Topic 1 (closed) — [notes/topic-01-llm-as-component.md](notes/topic-01-llm-as-component.md) — statelessness gap, "lost in the middle," temperature mechanics, syntactic vs semantic guarantees, danger/blast-radius framing
- Topic 2 (closed) — [notes/topic-02-prompting-context-engineering.md](notes/topic-02-prompting-context-engineering.md) — grounding/refusal clauses, few-shot, system-prompt dilution, full attention/Q-K-V/softmax/positional-encoding/multi-head/caching deep dive, delimiters/injection, negative instructions, chain-of-thought
- Topic 3 (closed) — [notes/topic-03-tool-function-calling.md](notes/topic-03-tool-function-calling.md) — tool_use/stop_reason mechanics, parallel-call correlation, tool-list dilution + retrieval mitigation, error handling/is_error, naming/description quality, tool_choice
- Topic 4 (closed) — [notes/topic-04-agent-loops-architectures.md](notes/topic-04-agent-loops-architectures.md) — workflow vs agent (locus of control), bounded autonomy, stopping conditions, single vs multi-agent, Plan-and-Execute vs ReAct, Reflection
- Topic 5 (closed) — [notes/topic-05-memory-and-state.md](notes/topic-05-memory-and-state.md) — compaction strategies, memory taxonomy, within-session vs cross-session as different problems, provenance/volatility schema, memory poisoning, memory vs state + idempotency
- Topic 6 (closed) — [notes/topic-06-rag-and-retrieval.md](notes/topic-06-rag-and-retrieval.md) — pipeline mechanics, grounding enforcement (gating/citation verification), chunking + contextual enrichment, failure locations, transformer vs retrieval embeddings (pooling, contrastive training), reranking, when RAG is the wrong tool
- Topic 7 (closed) — [notes/topic-07-mcp-and-tool-ecosystems.md](notes/topic-07-mcp-and-tool-ecosystems.md) — M×N and the LSP analogy, runtime discovery, tool-description poisoning/shadowing/rug-pull, confused deputy + lethal trifecta, deferred loading, and the build/consume mental models + checklist
