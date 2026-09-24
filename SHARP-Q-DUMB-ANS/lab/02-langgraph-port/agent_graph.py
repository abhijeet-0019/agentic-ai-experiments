"""
Lab 02 - the same agent as lab 01, as a LangGraph graph.

CONTROLLED EXPERIMENT. Two things are held constant:

  1. The tool BODIES are imported from lab 01, unchanged.
  2. The CONFIG (switches, descriptions, model) is imported from lab 01.

So orchestration is the only variable. Anything that differs in the output is
attributable to the framework, not to a rewrite.

Also held constant: use_responses_api=True, so both labs talk to the same
OpenAI endpoint. Without that, any comparison is confounded.
"""

# --- 1. imports + config -----------------------------------------------------

import json
import sys
from pathlib import Path
from typing import Annotated, Literal

import httpx
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_openai import ChatOpenAI
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import Field

LAB01 = Path(__file__).resolve().parents[1] / "01-raw-agent-loop"
sys.path.insert(0, str(LAB01))
import agent as lab01  # noqa: E402  -- importing also runs lab 01's load_dotenv

MODEL = lab01.MODEL

# lab 01's MAX_ITERS counted MODEL CALLS.
# LangGraph's recursion_limit counts SUPER-STEPS (node executions).
#   agent -> tools -> agent -> tools -> agent  =  5 super-steps, 3 model calls
# So the cap is renamed AND rescaled. This is not a like-for-like knob.
MODEL_CALL_BUDGET = lab01.MAX_ITERS
RECURSION_LIMIT = max(1, 2 * MODEL_CALL_BUDGET - 1)


# --- 2. tools: lab 01's bodies, schemas DERIVED instead of hand-written ------
#
# lab 01 hand-wrote 74 lines of JSON Schema. Here the schema comes from the
# signature. Two things must be re-added deliberately or they vanish:
#   - per-argument descriptions: Annotated[..., Field(description=...)]
#   - the append allowlist:      Literal[...]  (lab 01's ENFORCE_APPEND_TARGET)

AppendTarget = (
    Literal[tuple(lab01.APPEND_TARGETS)] if lab01.ENFORCE_APPEND_TARGET else str
)


@tool(description=lab01.SEARCH_DESC)
def search_notes(query: Annotated[str, Field(description="The search query.")]) -> str:
    return lab01.search_notes(query)


@tool(description=lab01.READ_DESC)
def read_note(
    file_name: Annotated[str, Field(description="The note file to read.")],
) -> str:
    return lab01.read_note(file_name)


@tool(description="Append content to a note file, creating it if it does not exist.")
def append_open_thread(
    file_name: Annotated[AppendTarget, Field(description="The note file to append to.")],
    content: Annotated[str, Field(description="The content to append.")],
) -> str:
    return lab01.append_open_thread(file_name, content)


TOOLS = [search_notes, read_note, append_open_thread]


# --- 3. visibility: a tap on the HTTP client --------------------------------
#
# THE FINDING: graph state is not the payload. To see the bytes that actually
# go over the wire -- what lab 01 got from one print() -- you have to reach
# BELOW the framework and instrument httpx. There is no supported hook that
# hands you the serialised request body.


def _clip(value, limit=100) -> str:
    text = str(value).replace("\n", "\\n")
    return text if len(text) <= limit else f"{text[:limit]}... (+{len(text) - limit} more chars)"


class WireTap:
    """Renders the literal request body, and accumulates token usage."""

    def __init__(self) -> None:
        self.calls = 0
        self.totals = {"input": 0, "output": 0}
        self.prev_input = 0

    def on_request(self, request: httpx.Request) -> None:
        self.calls += 1
        body = json.loads(request.content)
        items = body.get("input", [])

        print(f"\n--- model call {self.calls} ---")
        print(
            f"  POST {request.url.path}  "
            f"{len(request.content)} bytes  "
            f"{len(items)} items  "
            f"{len(body.get('tools', []))} tool schemas"
        )
        print(f"  input[{len(items)}]  (ALL of this is re-sent every turn)")

        for i, item in enumerate(items):
            kind = item.get("type")
            if kind == "function_call":
                print(f"    [{i}] tool_call    id={item.get('call_id')}")
                print(f"         -> {item.get('name')}({_clip(item.get('arguments'), 80)})")
            elif kind == "function_call_output":
                print(f"    [{i}] tool_result  id={item.get('call_id')}")
                print(f"         -> {_clip(item.get('output'))}")
            elif kind == "message" or "role" in item:
                content = item.get("content")
                if isinstance(content, list):
                    content = " ".join(
                        c.get("text", "") for c in content if isinstance(c, dict)
                    )
                print(f"    [{i}] {item.get('role', '?'):<9} {_clip(content)}")
            else:
                print(f"    [{i}] {kind}  {_clip(item)}")

    def record_usage(self, message) -> None:
        usage = getattr(message, "usage_metadata", None)
        if not usage:
            print("  tokens  <no usage_metadata on this message>")
            return

        delta = usage["input_tokens"] - self.prev_input if self.prev_input else 0
        self.totals["input"] += usage["input_tokens"]
        self.totals["output"] += usage["output_tokens"]
        self.prev_input = usage["input_tokens"]

        print(
            f"\n  tokens  in={usage['input_tokens']} (delta {delta:+d})  "
            f"out={usage['output_tokens']}"
        )
        print(
            f"  billed so far  input={self.totals['input']}  "
            f"output={self.totals['output']}  "
            f"-- every input token is paid again next turn"
        )

    @property
    def billed(self) -> int:
        return self.totals["input"] + self.totals["output"]


# --- 4. model + nodes --------------------------------------------------------

tap = WireTap()

llm = ChatOpenAI(
    model=MODEL,
    use_responses_api=True,  # match lab 01's endpoint exactly
    http_client=httpx.Client(event_hooks={"request": [tap.on_request]}),
).bind_tools(
    TOOLS,
    strict=True,  # NOT the default. This is what makes Literal a guarantee
    #               rather than a suggestion. See cross-cutting principle #8.
)


def agent(state: MessagesState) -> dict:
    """lab 01's `client.responses.create(...)` call."""
    message = llm.invoke(state["messages"])
    tap.record_usage(message)
    return {"messages": [message]}


# lab 01's dispatch_function_call(), 23 lines -> this.
#
# The lambda is not decoration. ToolNode's DEFAULT re-raises anything that
# isn't a validation error, so validate_file_path's ValueError would kill the
# run. lab 01 caught it with `except Exception` and let the model recover.
# The framework made a different choice; this restores lab 01's.
tools_node = ToolNode(
    TOOLS,
    handle_tool_errors=lambda e: f"Error executing tool: {e}",
)


def should_continue(state: MessagesState) -> str:
    """lab 01's `if not tool_calls: break`."""
    return "tools" if getattr(state["messages"][-1], "tool_calls", None) else END


# --- 5. the graph ------------------------------------------------------------
#
# lab 01's `while True` is not a loop here. It is topology: the edge from
# "tools" back to "agent" IS the cycle.
#
#     START -> agent -> should_continue? -> tools -+
#                            |                     |
#                           END          <---------+ (back to agent)


def build():
    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent)
    graph.add_node("tools", tools_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile()


# --- 6. runner ---------------------------------------------------------------

def run(prompt: str) -> None:
    app = build()

    try:
        final = app.invoke(
            {"messages": [HumanMessage(prompt)]},
            config={"recursion_limit": RECURSION_LIMIT},
        )
        print("\nFinal answer:")
        print(final["messages"][-1].text())
        print(f"\n[done] {tap.calls} model calls, {tap.billed} tokens billed.")

    except GraphRecursionError:
        # lab 01's cap printed a message and kept its transcript in a local
        # variable. Here the run raises and the state is GONE -- there is no
        # checkpointer, so nothing is resumable. That is the seam Part 2 tests.
        print(f"\n[cap] recursion_limit={RECURSION_LIMIT} hit "
              f"({MODEL_CALL_BUDGET} model calls) and the task is NOT finished.")
        print("[cap] The model was never told this limit exists.")
        print(f"[cap] {tap.billed} tokens billed for nothing.")
        print("[cap] State is lost: no checkpointer, nothing to resume.")


# --- 7. entrypoint -----------------------------------------------------------

def main() -> None:
    print("\npreset prompts:")
    for key, text in lab01.PRESETS.items():
        print(f"  {key}) {text}")

    choice = input("\npick 1-3, or type your own prompt: ").strip()
    prompt = lab01.PRESETS.get(choice) or choice
    if not prompt:
        print("nothing to do.")
        return

    print(f"\nprompt: {prompt}")
    run(prompt)


if __name__ == "__main__":
    print(
        f"Lab 02: LangGraph port.\n"
        f"  model            {MODEL}\n"
        f"  notes            {lab01.NOTES}\n"
        f"  switches         vague_desc={lab01.ARM_VAGUE_DESC}  "
        f"append_enum={lab01.ENFORCE_APPEND_TARGET}  "
        f"(bad_args is unreachable here -- schema is derived)\n"
        f"  model calls      {MODEL_CALL_BUDGET}  -> recursion_limit={RECURSION_LIMIT}\n"
        f"  strict           True"
    )

    if "--schemas" in sys.argv:
        print("\nderived tool schemas (compare against lab 01's 74 hand-written lines):")
        for t in TOOLS:
            print(json.dumps(convert_to_openai_tool(t, strict=True), indent=2))
        sys.exit(0)

    main()
