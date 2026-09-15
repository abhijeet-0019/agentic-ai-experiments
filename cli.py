import json
import uuid
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from src.post_agent.graph import build_graph

SESSIONS_FILE = Path("sessions.json")
DB_FILE = "checkpoints.db"


def load_sessions() -> dict:
    if SESSIONS_FILE.exists():
        return json.loads(SESSIONS_FILE.read_text())
    return {}


def save_sessions(sessions: dict) -> None:
    SESSIONS_FILE.write_text(json.dumps(sessions, indent=2))


def choose_thread(sessions: dict) -> tuple[str, bool]:
    """Returns (thread_id, is_new)."""
    in_progress = {tid: s for tid, s in sessions.items() if s["status"] == "in_progress"}

    if in_progress:
        ids = list(in_progress.keys())
        print("Existing in-progress sessions:")
        for i, tid in enumerate(ids, 1):
            print(f"  {i}. {in_progress[tid]['label']}")
        print("  0. Start a new session")

        choice = input("Pick a number (or 0 for new): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(ids):
            return ids[int(choice) - 1], False

    return str(uuid.uuid4()), True


def print_interrupt(payload: dict) -> None:
    print("\n--- Post for review ---")
    for i, post in enumerate(payload["posts"], 1):
        print(f"[{i}] {post}")
    tag = "FINAL attempt" if payload["is_final_attempt"] else f"attempt {payload['attempt']}"
    print(f"({tag})")
    print(payload["instructions"])


def print_outcome(state: dict) -> None:
    print("\n--- Session finished ---")
    if state["human_decision"] == "approved":
        print("Approved! Final post/thread:")
    else:
        print("Retries exhausted without approval. Last attempt:")
    for i, post in enumerate(state["output"], 1):
        print(f"[{i}] {post}")
    if state["human_decision"] == "rejected" and state["review_msg"]:
        print(f"Your last feedback: {state['review_msg'][-1]['text']}")


def main() -> None:
    sessions = load_sessions()
    thread_id, is_new = choose_thread(sessions)
    config = {"configurable": {"thread_id": thread_id}}

    with SqliteSaver.from_conn_string(DB_FILE) as checkpointer:
        graph = build_graph(checkpointer)

        if is_new:
            input_text = input("What did you work on / learn today? ").strip()
            sessions[thread_id] = {"label": input_text[:40], "status": "in_progress"}
            save_sessions(sessions)
            graph.invoke(
                {
                    "input_text": input_text,
                    "output": [],
                    "re_gen_count": 0,
                    "review_msg": [],
                },
                config,
            )

        while True:
            snapshot = graph.get_state(config)

            if not snapshot.next:
                print_outcome(snapshot.values)
                sessions[thread_id]["status"] = "done"
                save_sessions(sessions)
                break

            pending_interrupt = snapshot.tasks[0].interrupts[0]
            print_interrupt(pending_interrupt.value)
            answer = input("> ")
            graph.invoke(Command(resume=answer), config)


if __name__ == "__main__":
    main()
