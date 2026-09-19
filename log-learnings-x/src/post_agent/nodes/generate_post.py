from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from ..llm import get_llm
from ..prompts import GENERATE_POST_SYSTEM
from ..schemas import PostThread
from ..state import State

MAX_SCHEMA_RETRIES = 2


def _build_human_message(state: State) -> str:
    # .get(..., default) throughout, not bracket access: a caller other
    # than our own cli.py (e.g. LangGraph Studio's own submit form) isn't
    # guaranteed to seed every field on the very first run.
    lines = [f"Input:\n{state['input_text']}"]

    review_msg = state.get("review_msg") or []
    if review_msg:
        review_lines = "\n".join(f"- {r['text']}" for r in review_msg)
        lines.append(f"Review feedback so far:\n{review_lines}")

    output = state.get("output") or []
    if output:
        previous = "\n".join(output)
        lines.append(f"Your previous attempt:\n{previous}")

    return "\n\n".join(lines)


def generate_post(state: State) -> dict:
    llm = get_llm().with_structured_output(PostThread)
    messages = [
        SystemMessage(GENERATE_POST_SYSTEM),
        HumanMessage(_build_human_message(state)),
    ]

    result: PostThread | None = None
    last_error: ValidationError | None = None
    for _ in range(MAX_SCHEMA_RETRIES + 1):
        try:
            result = llm.invoke(messages)
            break
        except ValidationError as exc:
            last_error = exc
            violations = "; ".join(err["msg"] for err in exc.errors())
            messages.append(
                HumanMessage(
                    f"Your last response was invalid: {violations}. "
                    "Respond again, fixing this — every post must be at "
                    "most 280 characters."
                )
            )

    if result is None:
        raise last_error

    return {
        "output": result.posts,
        "re_gen_count": state.get("re_gen_count", 0) + 1,
    }
