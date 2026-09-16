# post-agent

A small LangGraph agent that turns a raw "what I worked on today" note into a
Twitter/X post (or thread, if it doesn't fit in one post), with a
human-in-the-loop review/regeneration loop before it's finalized.

Built as a learning project — the full design reasoning and decisions live in
[`hld.md`](hld.md) (the original design sketch) and [`notes.md`](notes.md)
(the resolved design record, including a revision checklist).

## How it works

```
START ──▶ generate_post ──▶ human_review ──┬─ approved  ──▶ END
                 ▲                          ├─ exhausted ──▶ END  (5 retries used)
                 │                          └─ retry ──▶ compact_reviews ──┘
                 └───────────────────────────────────────────┘
```

`generate_post` drafts a post from `input_text` (plus any prior feedback) →
`human_review` interrupts the graph and shows it to you → you approve it, or
reject with feedback to regenerate. After 5 rejected attempts the graph ends
anyway and returns the last draft. `compact_reviews` condenses the feedback
history before each retry so a long back-and-forth doesn't blow up the
prompt. See `notes.md` for the full design writeup.

## Requirements

- Python 3.10+
- An OpenAI API key (the agent calls `langchain-openai` under the hood)
- A LangSmith API key, only if you want tracing (optional)

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# then edit .env: set OPENAI_API_KEY (and optionally the LangSmith tracing vars)
```

## Run it in the terminal

```bash
python cli.py
```

Lists any in-progress session to resume, or starts a new one — asks what you
worked on, shows you the generated post, and lets you approve or send
feedback to regenerate. Session state is checkpointed to `checkpoints.db`
(SQLite) and session labels to `sessions.json`; both are local, gitignored
scratch files, safe to delete to start clean.

## Run it in LangGraph Studio (local, free — no cloud deployment)

```bash
pip install -e .          # makes `post_agent` importable as a package
langgraph dev
```

Then open the Studio URL printed in the terminal. This is a separate session
history from the terminal version — see `notes.md` Topic 10 for why.

## Project layout

```
cli.py                    # terminal driver: invoke/resume loop, input(), print()
langgraph.json             # LangGraph Studio manifest
pyproject.toml              # makes src/post_agent an installable package
src/post_agent/
├── state.py               # State schema + review_msg reducer
├── schemas.py              # structured-output models for LLM calls
├── prompts.py               # system messages
├── llm.py                    # chat model factory
├── nodes/                     # generate_post, human_review, compact_reviews
├── routers.py                  # routing logic (separate from nodes)
└── graph.py                     # wires nodes/edges/routers together
```
