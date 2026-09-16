from langchain_core.messages import HumanMessage, SystemMessage

from ..llm import get_llm
from ..prompts import COMPACT_REVIEWS_SYSTEM
from ..schemas import ReviewSummary
from ..state import ReplaceReviews, State

MAX_REVIEW_CHARS = 800


def compact_reviews(state: State) -> dict:
    review_msg = state["review_msg"]
    total_chars = sum(len(r["text"]) for r in review_msg)

    if total_chars <= MAX_REVIEW_CHARS:
        return {}

    review_lines = "\n".join(f"- {r['text']}" for r in review_msg)
    llm = get_llm().with_structured_output(ReviewSummary)
    messages = [
        SystemMessage(COMPACT_REVIEWS_SYSTEM),
        HumanMessage(f"Review history:\n{review_lines}"),
    ]
    result: ReviewSummary = llm.invoke(messages)

    return {"review_msg": ReplaceReviews(value=[{"text": result.summary}])}
