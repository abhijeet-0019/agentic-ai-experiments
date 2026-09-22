# Lab 01 — Raw agent loop, from scratch

## Why this exists

Topics 1-7 of the curriculum (see `../../syllabus.md` and `../../notes/`) were
covered conversationally. This build makes them physical. It was started at the
Topic 8 boundary (frameworks — build vs. buy) because **that question is
unanswerable without having written the loop manually once.** You cannot judge
what an abstraction buys you if you have never done the thing it abstracts.

## The goal is NOT an impressive artifact

It is to *feel* specific mechanics that have so far only been discussed:

- `stop_reason` flipping to `"tool_use"`, and the agent code reacting to it
- appending a `tool_result` block (with the matching `tool_use_id`) and watching
  the model continue from it
- a tool **erroring** (`is_error: true`) and the model self-correcting from the
  message you fed back
- the token count climbing on every single turn, because the whole transcript is
  resent each time (Topic 1: the model is stateless)
- hitting your **own** stopping condition — a max-iteration cap you wrote
- printing the exact `messages` array before a call, and realising that this
  visibility is the single most valuable debugging property in agent work

## Constraints (deliberate)

- **Raw SDK only. No framework.** No LangChain, LangGraph, CrewAI, Agent SDK.
- **Small.** Target ~100 lines. If it's growing past ~200, cut scope.
- **2-3 real tools**, hitting something real. Ideally drawn from actual work
  rather than a toy weather API — you'll keep poking at something you care
  about. *(Tool choice still to be decided — settle it at the start of the build
  session.)*
- **Print the full `messages` array** before each API call, at least while
  developing. Seeing the context grow is half the lesson.

## Things to deliberately hit (not avoid)

Let these happen rather than designing around them — each one is a topic made
concrete:

| Make it happen | Connects to |
|---|---|
| A tool call with bad arguments -> error fed back -> model retries | Topic 3 |
| The loop running longer than expected, hitting your iteration cap | Topic 4 |
| A long conversation where you notice the token cost per turn rising | Topic 1, 5 |
| Two tools with vague, overlapping descriptions -> wrong tool picked | Topic 3 |
| Calling the same side-effecting tool twice | Topic 5 (idempotency) |

## Stretch (only after the raw version works)

Port the same agent to LangGraph. Roughly an hour once the raw one exists, and
it converts Topic 8 from inherited opinion into first-hand judgement: *what did
the framework actually buy, and what did it hide?*

Specifically compare:
1. How fast can you see the exact prompt being sent, in each version?
2. Which parts of your 100 lines did the framework genuinely replace, and which
   did it merely rename?

## When done

Write up what was surprising in `../../notes/topic-08-frameworks.md` — gap-and-
insight style per `../../CLAUDE.md`, not a tutorial. The curriculum session
picks up Topic 8 from there.
