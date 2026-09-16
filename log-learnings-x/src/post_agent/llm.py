from functools import lru_cache

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()


@lru_cache
def get_llm() -> ChatOpenAI:
    return ChatOpenAI(model="gpt-4o", temperature=0.7)
