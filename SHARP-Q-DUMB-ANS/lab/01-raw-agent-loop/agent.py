"""Lab 01 - a raw agent loop, no framework. See BRIEF.md.

Provider: OpenAI Chat Completions (chosen over the Responses API on purpose --
Responses keeps state server-side, which would hide the statelessness lesson).
"""

# --- 1. imports + config -----------------------------------------------------
import json
import os
import sys
# import pathlib.Path as Path
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_PATH)

REPO = Path(__file__).resolve().parents[2]  # the curriculum repo root
NOTES = REPO / "notes"  # the notes subdir
MAX_ITERS = 3
MODEL = "gpt-4o-mini"  # the model to use for the agent loop

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)
# --- 2. the tools, as plain Python ------------------------------------------
# Three functions over the curriculum repo. No decorators, no registry magic.
# search_notes / read_note are deliberately overlapping (BRIEF: wrong tool picked).
# append_open_thread is deliberately side-effecting (BRIEF: idempotency).
def search_notes(query: str) -> str:
    """Search the notes dir for files containing the query string."""
    results = []
    for path in NOTES.glob("**/*.md"):
        if query.lower() in path.read_text().lower():
            results.append(str(path.relative_to(NOTES)))
            if len(results) >= 5:
                break
    return json.dumps(results)

def read_note(file_name: str) -> str:
    """Read the contents of a note file."""
    path = NOTES / file_name
    print(f"Reading note from path: {path}")  # Debugging line
    if not path.exists():
        return f"Error: {file_name} does not exist."
    return path.read_text()

def append_open_thread(file_name: str, content: str) -> str:
    """Append content to a note file, creating it if it doesn't exist."""
    path = NOTES / file_name
    with open(path, "a") as f:
        f.write(content + "\n")
    return f"Appended to {file_name}."

# --- 3. the schema the model actually sees ----------------------------------
# This is the ONLY thing the model knows about your tools. Not the code above.
tools_schema = {
    "functions": [
        {
            "name": "search_notes",
            "description": "Search the notes dir for files containing the query string.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query."}
                },
                "required": ["query"]
            }
        },
        {
            "name": "read_note",
            "description": "Read the contents of a note file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {"type": "string", "description": "The name of the note file to read."}
                },
                "required": ["file_name"]
            }
        },
        {
            "name": "append_open_thread",
            "description": "Append content to a note file, creating it if it doesn't exist.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {"type": "string", "description": "The name of the note file to append to."},
                    "content": {"type": "string", "description": "The content to append."}
                },
                "required": ["file_name", "content"]
            }
        }
    ]
}

# --- 4. dispatch: name + JSON string -> result string -----------------------
# Every failure here must come back as a *string the model can read*, never a
# raised exception. This is where self-correction is won or lost.
def dispatch_function_call(func_name: str, func_args_json: str) -> str:
    """Dispatch a function call by name and JSON string of arguments."""
    try:
        func_args = json.loads(func_args_json)
    except json.JSONDecodeError as e:
        return f"Error: Failed to parse arguments JSON: {e}"

    if func_name == "search_notes":
        return search_notes(**func_args)
    elif func_name == "read_note":
        return read_note(**func_args)
    elif func_name == "append_open_thread":
        return append_open_thread(**func_args)
    else:
        return f"Error: Unknown function '{func_name}'"


# --- 5. visibility ----------------------------------------------------------
# Print the exact messages array before each call. The BRIEF calls this half
# the lesson; it is not debug cruft, it is the point.
def print_messages(messages):
    """Print the messages array in a readable format."""
    print("Messages so far:")

    for msg in messages:
        role = msg.get("role", "unknown")

        print(f"{role}: {msg.get('content', '')}")

        if msg.get("function_call"):
            func_name = msg["function_call"]["name"]
            func_args = msg["function_call"]["arguments"]
            print(f"  Function call: {func_name}({func_args})")

        if role == "function":
            print(f"  Function result: {msg.get('content', '')}")

# --- 6. the loop ------------------------------------------------------------
def agent_loop(initial_prompt: str, max_iters: int = MAX_ITERS) -> None:
    """Run the agent loop with the given initial prompt."""
    messages = [{"role": "user", "content": initial_prompt}]
    for i in range(max_iters):
        print(f"\n--- Iteration {i + 1} ---")
        print_messages(messages)
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            functions=tools_schema["functions"],
            function_call="auto",
            temperature=0.7
        )
        message = response.choices[0].message
        print(f"Model response: {message}")
        if message.function_call:
            func_name = message.function_call.name
            func_args_json = message.function_call.arguments
            messages.append({"role": "assistant", "content": None, "function_call": {"name": message.function_call.name, "arguments": message.function_call.arguments}} if message.function_call else {"role": "assistant", "content": message.content})
            result = dispatch_function_call(func_name, func_args_json)
            messages.append({"role": "function", "name": func_name, "content": result})
            print(messages)  # Debugging line to show the function result
        else:
            print_messages(messages)
            break

# --- 7. entrypoint ----------------------------------------------------------
def main():
    initial_prompt = "Search for notes about 'agent loops' and read the first one."
    print(f"Starting agent loop with initial prompt: {initial_prompt}")
    prompt = input("Press Enter to start the loop... OR write your own prompt and press Enter: ")
    if prompt:
        initial_prompt = prompt
    agent_loop(initial_prompt)

if __name__ == "__main__":
    # This is the only thing that runs when you do `python agent.py`.
    # It is deliberately minimal, to keep the focus on the loop itself.
    print(f"Lab 01: raw agent loop, no framework. See BRIEF.md. Model: {MODEL}")
    main()
