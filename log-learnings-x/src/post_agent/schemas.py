from pydantic import BaseModel, Field, field_validator

MAX_POST_LENGTH = 280


class PostThread(BaseModel):
    """Structured response generate_post asks the LLM for."""

    posts: list[str] = Field(
        description=(
            "The post, split into a thread only if it cannot fit in one "
            f"post. Each entry must be <= {MAX_POST_LENGTH} characters. "
            "Prefer compressing content over leaving a tiny trailing post."
        )
    )

    @field_validator("posts")
    @classmethod
    def check_length(cls, posts: list[str]) -> list[str]:
        for i, post in enumerate(posts):
            if len(post) > MAX_POST_LENGTH:
                raise ValueError(
                    f"post #{i} is {len(post)} chars, over the "
                    f"{MAX_POST_LENGTH} limit"
                )
        return posts


class ReviewSummary(BaseModel):
    """Structured response compact_reviews asks the LLM for."""

    summary: str = Field(
        description="A single comment condensing every actionable point "
        "from the review history, preserving all distinct feedback."
    )
