# High-Level Design (original sketch)

This is the original design sketch this project started from, reformatted
for readability but otherwise left as-is — including the rough edges and
open questions it started with. See [`notes.md`](notes.md) for the
resolved design those questions turned into, and its "Quick revision"
section for exactly where this original sketch needed correcting.

## Nodes & edges

```
node1 -> generate_post
node2 -> human_review

edge1 -> start --> generate_post
edge2 -> generate_post --> human_review
edge3 -> human_review --> CONDITIONAL(
    if 'approved':
        --> finish
    else:
        --> generate_post
) -- interrupt before
```

## State

```
state:
    post_gen_status: True/False       --- bool
    post_review_status: PASS/FAIL     --- string
    re_gen_count: 0-5                 --- int
    input_text:                       --- string
    review_msg: {}                    --- append/reducer - to be converted to proper
                                           format and summarize in case of repetitive
                                           or large messages; APPEND only, so that
                                           along with the input message, the response
                                           and review also remain in the context
    output: {}                        --- add/replace only, json - because if the
                                           response is larger than the single-post
                                           280-char limit, we have to move from a
                                           single post to multiple posts (i.e. threads,
                                           as on X/Twitter)
```

## System prompt

```
SYSTEM_MSG/PROMPT: """
You are a techie with passion and proficiency in system design, AI architectures,
AWS architectures, Python, etc., with 10+ years of working experience. You are
also good with Twitter/X content/post writing, and know how to write engaging
and interesting posts and threads about the topics of your domain.

Here, you have an objective: converting the input given by the user into a
Twitter/X post (and, if content demands, threads in the output, in proper
format).

Here are some rules about writing:
- Keep it human, use short sentences, write clearly in simple English.
- Be passionate.
- If some placeholders are required to be filled by the user, keep the
  necessary space.
- Remember the max number of chars a post can have is 280, so if the post is
  going beyond that, convert that to a thread (multiple posts).
- Don't write an essay on topics/concepts the user doesn't know - only
  include what the user has given in the input; you can refine to include
  content you feel the user is aware of but somehow missed in the input.
- The objective of this writing is to log the daily work and learnings of the
  user, to be exposed/shared with the community using X/Twitter, to build
  their online presence and personal brand.
- The objective is also to build connections - to people interested in
  similar topics, or experts in similar profiles.

Here is the input: {input}

Here is the review of the previous response of yours - please update the
post(s) as per the review instructions of the user.
Here is the previous response: {last_res}
Here is the review by the user on the last response: {last_res}
"""
```

## Pseudocode

```python
def full_msg():
    input
    review
    last_res


def generate_post():
    if state.re_gen_count > 4:
        return END  # msg: max attempts exhausted, kindly retry -- here is the
                     # snapshot of our discussion so far -- state

    input = state.input_text
    full_msg[input] = input

    if len(review_msg) > 0:
        full_msg[review] = state.review_msg[-1]
        full_msg[last_res] = state.output

    call_llm(SYSTEM_MSG.append(full_msg))


def human_review():
    res = input("here is your post/s:")
    if res != "" OR "approved":
        return END
    return generate_post
```
