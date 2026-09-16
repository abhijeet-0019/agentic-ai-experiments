from langgraph.graph import END

from .state import MAX_REGEN_COUNT, State


def route_after_review(state: State) -> str:
    if state["human_decision"] == "approved":
        return "approved"

    if state["re_gen_count"] >= MAX_REGEN_COUNT:
        return "exhausted"

    return "retry"
