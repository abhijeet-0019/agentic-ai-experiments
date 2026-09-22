"""Lab 01 - a raw agent loop, no framework. See BRIEF.md.

Provider: OpenAI Chat Completions (chosen over the Responses API on purpose --
Responses keeps state server-side, which would hide the statelessness lesson).
"""

# --- 1. imports + config -----------------------------------------------------


# --- 2. the tools, as plain Python ------------------------------------------
# Three functions over the curriculum repo. No decorators, no registry magic.
# search_notes / read_note are deliberately overlapping (BRIEF: wrong tool picked).
# append_open_thread is deliberately side-effecting (BRIEF: idempotency).


# --- 3. the schema the model actually sees ----------------------------------
# This is the ONLY thing the model knows about your tools. Not the code above.


# --- 4. dispatch: name + JSON string -> result string -----------------------
# Every failure here must come back as a *string the model can read*, never a
# raised exception. This is where self-correction is won or lost.


# --- 5. visibility ----------------------------------------------------------
# Print the exact messages array before each call. The BRIEF calls this half
# the lesson; it is not debug cruft, it is the point.


# --- 6. the loop ------------------------------------------------------------


# --- 7. entrypoint ----------------------------------------------------------
