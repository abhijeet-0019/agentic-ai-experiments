"""
Lab 02b - the floor. The same agent via LangGraph's prebuilt ReAct agent.

This exists purely to answer "how few lines can this be?" It is NOT the
comparison file -- `agent_graph.py` is, because it keeps the mapping to lab 01
visible. This one hides everything, which is the point of showing it.

Note what you lose: no wire visibility, no token accounting, no control over
the loop. You get a working agent and no idea what it sent.
"""

import sys
from pathlib import Path

from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_graph import MODEL, RECURSION_LIMIT, TOOLS, lab01  # noqa: E402

app = create_react_agent(f"openai:{MODEL}", TOOLS)


def main() -> None:
    for key, text in lab01.PRESETS.items():
        print(f"  {key}) {text}")
    choice = input("\npick 1-3, or type your own prompt: ").strip()
    prompt = lab01.PRESETS.get(choice) or choice

    result = app.invoke(
        {"messages": [HumanMessage(prompt)]},
        config={"recursion_limit": RECURSION_LIMIT},
    )
    print("\nFinal answer:")
    print(result["messages"][-1].text())


if __name__ == "__main__":
    main()
