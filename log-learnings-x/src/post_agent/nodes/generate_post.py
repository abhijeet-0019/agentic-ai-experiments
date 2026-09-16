from langchain_core.messages import HumanMessage, SystemMessage

from ..llm import get_llm
from ..prompts import GENERATE_POST_SYSTEM
from ..schemas import PostThread
from ..state import State


def _build_human_message(state: State) -> str:
    lines = [f"Input:\n{state['input_text']}"]

    if state["review_msg"]:
        review_lines = "\n".join(f"- {r['text']}" for r in state["review_msg"])
        lines.append(f"Review feedback so far:\n{review_lines}")

    if state["output"]:
        previous = "\n".join(state["output"])
        lines.append(f"Your previous attempt:\n{previous}")

    return "\n\n".join(lines)


def generate_post(state: State) -> dict:
    llm = get_llm().with_structured_output(PostThread)
    messages = [
        SystemMessage(GENERATE_POST_SYSTEM),
        HumanMessage(_build_human_message(state)),
    ]
    result: PostThread = llm.invoke(messages)

    return {
        "output": result.posts,
        "re_gen_count": state["re_gen_count"] + 1,
    }
