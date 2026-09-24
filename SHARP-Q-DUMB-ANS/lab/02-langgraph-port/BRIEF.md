# Lab 02 — the same agent, in LangGraph

Not a port for its own sake. A **controlled experiment**: lab 01's tool
functions are imported unchanged, so orchestration is the only variable.

## The question
What did the framework genuinely *replace*, and what did it merely *rename* or
*hide*?

## Baseline to beat (lab 01, non-blank non-comment)
| section | lines |
|---|---|
| tool schemas | 74 |
| the loop | 57 |
| dispatch | 23 |
| **visibility** | **45** |
| tools | 38 |
| config + entrypoint | 54 |
| **total** | **291** |

## Probes (verified against langgraph 1.2.12 before building)
| Raw-loop finding | What LangGraph does |
|---|---|
| Bad args -> error -> retry | **Cannot be constructed.** Schema is derived from the signature. |
| Error message = next turn's prompt | Default messages name the fix — better than lab 01's. |
| Tool body raises | **Propagates and kills the run.** lab 01 caught it. |
| Schema enum | Survives (`Literal` -> `const`/`enum`). `strict` available, NOT default. |
| Per-arg descriptions | **Dropped** unless `Annotated[..., Field(description=...)]`. |
| Print the payload | State != payload. Needs a callback. **Time this.** |

## Run the same four experiments
Presets 1-3 plus `ARM_BAD_ARGS`, same as lab 01, and diff the observations.

## When done
`notes/topic-08-frameworks.md` Part 2, then close Topic 8.
