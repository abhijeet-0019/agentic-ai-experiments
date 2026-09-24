"""
Lab 02b - phase 2: the thing a raw loop cannot do at any line count.

Lab 01 had a human-in-the-loop gate. It was `input()`. If the process died,
the run was gone -- no state, no resume, tokens already spent.

This adds two things that are NOT the same as lab 01's:

  1. A gate that fires on ACTION CLASS (write tools), not on model confidence.
     This is cross-cutting principle #1: system-initiated gating. The model
     gets no vote on whether approval is needed.

  2. DURABLE pause. State goes to SQLite, the process exits, and a LATER
     process resumes mid-graph.

NOTE the trap: every LangGraph tutorial uses InMemorySaver, which dies with the
process and therefore provides NONE of this. Durability needs a real backend
(langgraph-checkpoint-sqlite, a separate package).

Usage:
    python agent_graph_hitl.py "<prompt>"          # start; may pause and exit
    python agent_graph_hitl.py --state   <thread>  # inspect a paused run
    python agent_graph_hitl.py --approve <thread>  # resume, allow the write
    python agent_graph_hitl.py --deny    <thread> "reason"
"""

import json
import sqlite3
import sys
import uuid
from pathlib import Path

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import Command, interrupt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_graph import (  # noqa: E402
    RECURSION_LIMIT,
    TOOLS,
    agent,
    lab01,
    should_continue,
    tap,
    tools_node,
)

DB = Path(__file__).resolve().parent / "checkpoints.sqlite"

# Gate on what the action IS, never on how the model feels about it.
WRITE_TOOLS = {"append_open_thread"}


# --- the gate ----------------------------------------------------------------

def gate(state: MessagesState) -> dict:
    """Pause before any write. Returns nothing if there is nothing to gate."""
    last = state["messages"][-1]
    calls = getattr(last, "tool_calls", None) or []
    writes = [c for c in calls if c["name"] in WRITE_TOOLS]

    if not writes:
        return {}

    # Execution stops HERE. State is persisted. The process may now die.
    decision = interrupt(
        {
            "reason": "write tool requires human approval",
            "pending": [{"name": c["name"], "args": c["args"], "id": c["id"]} for c in writes],
        }
    )

    if isinstance(decision, dict) and decision.get("approved"):
        return {}

    note = (decision or {}).get("note", "no reason given") if isinstance(decision, dict) else str(decision)

    # Every tool_call in the turn must be answered or the next request is
    # invalid -- so a denial denies the whole turn. (Simplification: a mixed
    # read+write turn loses its reads too. Noted, not fixed.)
    return {
        "messages": [
            ToolMessage(
                content=f"Denied by human reviewer: {note}",
                tool_call_id=c["id"],
                status="error",
            )
            for c in calls
        ]
    }


def after_gate(state: MessagesState) -> str:
    """If the gate injected denials, skip execution and let the model react."""
    return "agent" if isinstance(state["messages"][-1], ToolMessage) else "tools"


# --- the graph ---------------------------------------------------------------
#
#   START -> agent -> should_continue -> { END | gate }
#                                          gate -> after_gate -> { tools | agent }
#                                          tools -> agent

def build_app():
    saver = SqliteSaver(sqlite3.connect(DB, check_same_thread=False))

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent)
    graph.add_node("gate", gate)
    graph.add_node("tools", tools_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "gate", END: END})
    graph.add_conditional_edges("gate", after_gate, {"tools": "tools", "agent": "agent"})
    graph.add_edge("tools", "agent")

    return graph.compile(checkpointer=saver)


# --- driving it --------------------------------------------------------------

def _report(app, result, thread: str) -> None:
    if "__interrupt__" in result:
        payload = result["__interrupt__"][0].value
        print("\n[PAUSED] durable interrupt -- state is on disk, process can exit now.")
        print(json.dumps(payload, indent=2))
        print(f"\n  approve:  python {Path(__file__).name} --approve {thread}")
        print(f"  deny   :  python {Path(__file__).name} --deny    {thread} \"reason\"")
        return

    print("\nFinal answer:")
    print(result["messages"][-1].text())
    print(f"\n[done] {tap.calls} model calls this process, {tap.billed} tokens billed.")


def start(prompt: str) -> None:
    thread = uuid.uuid4().hex[:8]
    print(f"thread: {thread}\nprompt: {prompt}")
    app = build_app()
    cfg = {"configurable": {"thread_id": thread}, "recursion_limit": RECURSION_LIMIT}
    try:
        _report(app, app.invoke({"messages": [HumanMessage(prompt)]}, config=cfg), thread)
    except GraphRecursionError:
        print(f"\n[cap] recursion_limit={RECURSION_LIMIT} hit; {tap.billed} tokens billed.")
        print(f"[cap] UNLIKE lab 01, state survives: --state {thread}")


def resume(thread: str, decision: dict) -> None:
    app = build_app()
    cfg = {"configurable": {"thread_id": thread}, "recursion_limit": RECURSION_LIMIT}
    print(f"resuming {thread} with {decision}")
    try:
        _report(app, app.invoke(Command(resume=decision), config=cfg), thread)
    except GraphRecursionError:
        print(f"\n[cap] recursion_limit={RECURSION_LIMIT} hit; {tap.billed} tokens billed.")


def show_state(thread: str) -> None:
    app = build_app()
    snap = app.get_state({"configurable": {"thread_id": thread}})
    if not snap.values:
        print(f"no state for thread {thread}")
        return
    print(f"thread {thread}  next={snap.next}")
    for i, m in enumerate(snap.values.get("messages", [])):
        kind = type(m).__name__
        detail = getattr(m, "tool_calls", None) or m.content
        print(f"  [{i}] {kind:14} {str(detail)[:88]}")


# --- entrypoint --------------------------------------------------------------

if __name__ == "__main__":
    args = sys.argv[1:]

    if not args:
        print(__doc__)
        print("presets:")
        for k, v in lab01.PRESETS.items():
            print(f"  {k}) {v}")
        sys.exit(0)

    if args[0] == "--state":
        show_state(args[1])
    elif args[0] == "--approve":
        resume(args[1], {"approved": True})
    elif args[0] == "--deny":
        resume(args[1], {"approved": False, "note": args[2] if len(args) > 2 else "denied"})
    else:
        start(lab01.PRESETS.get(args[0]) or args[0])
