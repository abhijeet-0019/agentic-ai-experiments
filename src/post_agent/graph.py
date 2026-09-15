from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from .nodes.compact_reviews import compact_reviews
from .nodes.generate_post import generate_post
from .nodes.human_review import human_review
from .routers import route_after_review
from .state import State


def _build_wiring() -> StateGraph:
    builder = StateGraph(State)

    builder.add_node("generate_post", generate_post)
    builder.add_node("human_review", human_review)
    builder.add_node("compact_reviews", compact_reviews)

    builder.add_edge(START, "generate_post")
    builder.add_edge("generate_post", "human_review")
    builder.add_conditional_edges(
        "human_review",
        route_after_review,
        {
            "approved": END,
            "exhausted": END,
            "retry": "compact_reviews",
        },
    )
    builder.add_edge("compact_reviews", "generate_post")

    return builder


def build_graph(checkpointer: BaseCheckpointSaver):
    """Used by cli.py — persistence is our own explicit SqliteSaver."""
    return _build_wiring().compile(checkpointer=checkpointer)


# Used by `langgraph dev` (see langgraph.json) — no checkpointer here;
# the dev server manages its own persistence layer for this entry point.
graph = _build_wiring().compile()
