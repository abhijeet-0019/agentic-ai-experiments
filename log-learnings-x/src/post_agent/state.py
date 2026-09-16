from dataclasses import dataclass
from typing import Annotated, Literal, TypedDict

MAX_REGEN_COUNT = 5


class ReviewEntry(TypedDict):
    text: str


@dataclass
class ReplaceReviews:
    """Tag wrapping a condensed history. Signals the reducer to discard
    the old review_msg list instead of appending."""
    value: list[ReviewEntry]


def review_msg_reducer(
    current: list[ReviewEntry],
    new: ReviewEntry | ReplaceReviews | list[ReviewEntry],
) -> list[ReviewEntry]:
    if isinstance(new, ReplaceReviews):
        return list(new.value)
    # A ReviewEntry is always a dict — a plain list here can only mean
    # "set/seed the whole list directly" (e.g. raw JSON from Studio's UI,
    # which has no way to express the ReplaceReviews tag), never a single
    # entry to append.
    if isinstance(new, list):
        return list(new)
    return current + [new]


class State(TypedDict):
    input_text: str
    output: list[str]
    re_gen_count: int
    review_msg: Annotated[list[ReviewEntry], review_msg_reducer]
    human_decision: Literal["approved", "rejected"]
