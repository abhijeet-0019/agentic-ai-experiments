"""
Lab 01 - a raw agent loop, no framework.

Provider: OpenAI Responses API.

The agent loop is intentionally implemented manually so that
tool calling, dispatching, and conversation state remain visible.

The Responses API can optionally maintain conversation state using response
IDs. For this lab we deliberately do NOT use that feature. Instead the
application explicitly maintains input_items, so that the stateless
request/response architecture stays visible.
"""

# --- 1. imports + config -----------------------------------------------------

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_PATH)

REPO = Path(__file__).resolve().parents[0]
NOTES = REPO / "sample_notes"

MAX_ITERS = 1
MODEL = "gpt-4o-mini"

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


# --- experiment switches -----------------------------------------------------
# Each one arms a row of BRIEF.md's "things to deliberately hit" table.
# Flip one at a time; changing two at once makes the result unreadable.

# A) Two tools with vague, overlapping descriptions -> wrong tool picked.
#    True  = search_notes and read_note both say "look up the info".
#    False = honest, distinct descriptions.
ARM_VAGUE_DESC = False

# B) Schema advertises "q"; search_notes() actually takes "query".
#    The model will send a schema-valid argument your Python cannot accept.
#    Watch whether the TypeError text is a recovery instruction or a dead end.
ARM_BAD_ARGS = False

# C) Constrain the append target in the SCHEMA (an enum) rather than trusting
#    a free string. With strict=True the model *cannot* emit anything else.
#    False = free-form file_name, containment enforced only in code.
ENFORCE_APPEND_TARGET = False
APPEND_TARGETS = ["open_threads.md"]

# Print raw SDK objects instead of the readable rendering.
RAW_ITEMS = False


def validate_file_path(file_name: str) -> Path:
    """Containment check: the resolved path must stay inside NOTES."""
    path = (NOTES / file_name).resolve()
    if not path.is_relative_to(NOTES.resolve()):
        raise ValueError(f"Error: {file_name} is outside the notes directory.")
    return path


def _available_notes() -> list[str]:
    if not NOTES.is_dir():
        return []
    return sorted(f.name for f in NOTES.iterdir() if f.is_file())


# --- 2. tools: plain Python functions ----------------------------------------

def search_notes(query: str) -> str:
    """Find note files whose name matches a keyword."""
    if not NOTES.is_dir():
        return f"Error: the notes directory ({NOTES}) does not exist."

    results = []
    for note_file in NOTES.iterdir():
        if note_file.is_file():
            normalized_name = note_file.stem.replace("_", " ").lower()
            if query.lower() in normalized_name:
                results.append(note_file.name)

    if results:
        return f"Search results for '{query}': {results}"
    return (
        f"No notes matched '{query}'. "
        f"Available notes: {_available_notes()}"
    )


def read_note(file_name: str) -> str:
    """Read the contents of a note file."""
    path = validate_file_path(file_name)
    print(f"  [tool] reading {path}")

    if not path.exists():
        # The error message IS the next turn's prompt. Listing what exists
        # turns a guessing loop into a one-step recovery.
        return (
            f"Error: '{file_name}' does not exist. "
            f"Available notes: {_available_notes()}"
        )

    return path.read_text()


def append_open_thread(file_name: str, content: str) -> str:
    """Append one line to a note file.

    The timestamp is generated HERE, in code -- never accepted from the model.
    A value your runtime can compute must never be a tool parameter; that is
    how a hallucinated date got written into a real note earlier in this lab.
    """
    path = validate_file_path(file_name)

    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    line = f"[{stamp}] {content}"

    with open(path, "a") as f:
        f.write(line + "\n")

    # Echo the exact bytes written, so the model can see what it just did.
    return f"Appended to {file_name}: {line}"


# --- 3. tool schemas ---------------------------------------------------------
#
# This is what the MODEL sees.
# It does NOT see the Python implementations above.

SEARCH_PARAM = "q" if ARM_BAD_ARGS else "query"

if ARM_VAGUE_DESC:
    SEARCH_DESC = "look up the information in the notes"
    READ_DESC = "look up the info"
else:
    SEARCH_DESC = (
        "Find note files whose FILENAME matches a keyword. "
        "Returns a list of filenames. Use this when you do not know the exact filename."
    )
    READ_DESC = (
        "Read and return the full text of ONE note file. "
        "Requires the exact filename, including extension."
    )

_append_file_prop = (
    {"type": "string", "enum": APPEND_TARGETS, "description": "The note file to append to."}
    if ENFORCE_APPEND_TARGET
    else {"type": "string", "description": "The note file to append to."}
)

tools = [
    {
        "type": "function",
        "name": "search_notes",
        "description": SEARCH_DESC,
        "parameters": {
            "type": "object",
            "properties": {
                SEARCH_PARAM: {
                    "type": "string",
                    "description": "The search query.",
                }
            },
            "required": [SEARCH_PARAM],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "read_note",
        "description": READ_DESC,
        "parameters": {
            "type": "object",
            "properties": {
                "file_name": {
                    "type": "string",
                    "description": "The note file to read.",
                }
            },
            "required": ["file_name"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "append_open_thread",
        "description": (
            "Append content to a note file, creating it if it does not exist."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_name": _append_file_prop,
                "content": {
                    "type": "string",
                    "description": "The content to append.",
                },
            },
            "required": ["file_name", "content"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


# --- 4. dispatch -------------------------------------------------------------

def dispatch_function_call(func_name: str, func_args_json: str) -> str:
    """
    Convert the model's function call into an actual Python call.

    Every failure is returned as text so the model can see the failure
    and potentially correct itself.
    """
    try:
        func_args = json.loads(func_args_json)
    except json.JSONDecodeError as e:
        return f"Error: Failed to parse arguments JSON: {e}"

    try:
        if func_name == "search_notes":
            return search_notes(**func_args)

        elif func_name == "read_note":
            return read_note(**func_args)

        elif func_name == "append_open_thread":
            return append_open_thread(**func_args)

        else:
            return f"Error: Unknown function '{func_name}'"

    except TypeError as e:
        # Schema/signature mismatch lands here (see ARM_BAD_ARGS).
        return f"Error executing {func_name}: {e}"

    except Exception as e:
        return f"Error executing {func_name}: {e}"


# --- 5. visibility -----------------------------------------------------------

def _clip(value, limit=100) -> str:
    text = str(value).replace("\n", "\\n")
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... (+{len(text) - limit} more chars)"


def print_input_items(items):
    """Render the exact array that is about to be re-sent to the model."""
    print(f"\n  input_items[{len(items)}]  (ALL of this is re-sent every turn)")

    for i, item in enumerate(items):
        if RAW_ITEMS:
            print(f"    [{i}] {item}")
            continue

        if isinstance(item, dict):
            if item.get("type") == "function_call_output":
                print(f"    [{i}] tool_result  id={item['call_id']}")
                print(f"         -> {_clip(item['output'])}")
            else:
                print(f"    [{i}] {item.get('role', '?'):<9} {_clip(item.get('content', ''))}")
            continue

        kind = getattr(item, "type", "?")
        if kind == "function_call":
            print(f"    [{i}] tool_call    id={item.call_id}")
            print(f"         -> {item.name}({_clip(item.arguments, 80)})")
        elif kind == "message":
            texts = [getattr(c, "text", "") for c in (getattr(item, "content", None) or [])]
            print(f"    [{i}] assistant  {_clip(' '.join(texts))}")
        else:
            print(f"    [{i}] {kind}  {_clip(item)}")


def print_usage(usage, prev_input, totals):
    """Show the climb, not just the number."""
    delta = usage.input_tokens - prev_input if prev_input else 0
    cached = usage.input_tokens_details.cached_tokens

    totals["input"] += usage.input_tokens
    totals["output"] += usage.output_tokens

    print(
        f"\n  tokens  in={usage.input_tokens} (delta {delta:+d})  "
        f"out={usage.output_tokens}  cached={cached}"
    )
    print(
        f"  billed so far  input={totals['input']}  output={totals['output']}  "
        f"-- every input token is paid again next turn"
    )
    if cached == 0 and usage.input_tokens < 1024:
        print("  (no cache: OpenAI needs a >=1024-token prefix before anything caches)")

    return usage.input_tokens


# --- 6. the raw agent loop ---------------------------------------------------

def agent_loop(initial_prompt: str, max_iters: int = MAX_ITERS) -> None:

    # We deliberately maintain state ourselves.
    input_items = [
        {
            "role": "user",
            "content": initial_prompt,
        }
    ]

    count = 0
    budget = max_iters
    prev_input = 0
    totals = {"input": 0, "output": 0}

    while True:
        count += 1
        print(f"\n--- Iteration {count} ---")

        print_input_items(input_items)

        response = client.responses.create(
            model=MODEL,
            input=input_items,
            tools=tools,
            tool_choice="auto",
        )

        prev_input = print_usage(response.usage, prev_input, totals)

        # Add EVERYTHING the model produced to our conversation state.
        input_items += response.output

        # Find tool calls in the response.
        tool_calls = [
            item
            for item in response.output
            if item.type == "function_call"
        ]

        # No tool call means the model has produced its final answer.
        if not tool_calls:
            print("\nFinal answer:")
            print(response.output_text)
            print(f"\n[done] {count} iterations, {totals['input'] + totals['output']} tokens billed.")
            break

        # Execute every requested tool.
        for tool_call in tool_calls:
            print(f"\n  tool_call  {tool_call.name}({tool_call.arguments})")

            result = dispatch_function_call(
                tool_call.name,
                tool_call.arguments,
            )

            print(f"  result     {_clip(result, 200)}")

            # Give the tool result back to the model.
            # One output per call, keyed by call_id -- the API pairs them
            # before the model is ever invoked.
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": tool_call.call_id,
                    "output": result,
                }
            )

        if count >= budget:
            print(f"\n[cap] {count} iterations used and the task is NOT finished.")
            print("[cap] The model was never told this limit exists -- it cannot pace itself.")
            answer = input(f"[cap] Continue for {max_iters} more? (y/n): ")

            if answer.strip().lower() == "y":
                budget += max_iters
                continue

            print(f"[cap] Stopping at {count} iterations with NO final answer.")
            print(f"[cap] {totals['input'] + totals['output']} tokens billed for nothing.")
            break


# --- 7. entrypoint -----------------------------------------------------------

PRESETS = {
    "1": "what's in the open threads note?",
    "2": 'add a line to the open threads note saying "review lab 01 notes", then add the same line again.',
    "3": "read every note and give me a one-line summary of each",
}


def main():
    print("\npreset prompts:")
    for key, text in PRESETS.items():
        print(f"  {key}) {text}")

    choice = input("\npick 1-3, or type your own prompt: ").strip()
    initial_prompt = PRESETS.get(choice) or choice

    if not initial_prompt:
        print("nothing to do.")
        return

    print(f"\nprompt: {initial_prompt}")
    agent_loop(initial_prompt)


if __name__ == "__main__":
    print(
        f"Lab 01: raw agent loop, no framework.\n"
        f"  model  {MODEL}\n"
        f"  notes  {NOTES}\n"
        f"  switches  vague_desc={ARM_VAGUE_DESC}  "
        f"bad_args={ARM_BAD_ARGS}  append_enum={ENFORCE_APPEND_TARGET}\n"
        f"  max_iters  {MAX_ITERS}"
    )
    main()
