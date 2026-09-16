from langgraph.types import interrupt

from ..state import MAX_REGEN_COUNT, State

APPROVAL_WORDS = {"", "y", "yes", "approved"}


def human_review(state: State) -> dict:
    attempt = state["re_gen_count"]
    payload = {
        "posts": state["output"],
        "attempt": attempt,
        "is_final_attempt": attempt >= MAX_REGEN_COUNT,
        "instructions": (
            "Press Enter or type 'y' to approve, or type your feedback "
            "to request changes."
        ),
    }
    answer = interrupt(payload).strip()

    if answer.lower() in APPROVAL_WORDS:
        return {"human_decision": "approved"}

    return {
        "human_decision": "rejected",
        "review_msg": {"text": answer},
    }
