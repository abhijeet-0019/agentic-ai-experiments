# post-agent

A small LangGraph agent that turns a raw "what I worked on today" note into a
Twitter/X post (or thread, if it doesn't fit in one post), with a
human-in-the-loop review/regeneration loop before it's finalized.

Built as a learning project — the full design reasoning and decisions live in
[`hld.md`](hld.md) (the original design sketch) and [`notes.md`](notes.md)
(the resolved design record, including a revision checklist).

## How it works

`generate_post` drafts a post → `human_review` pauses and shows it to you →
approve it, or reject with feedback to regenerate (up to 5 attempts,
`compact_reviews` condenses the feedback history if it grows large). See
`notes.md` for the full graph design.

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
feedback to regenerate.

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
