"""Gemini LLM provider. Implemented by ``ws-g-gemini-llm``."""

from __future__ import annotations


def generate(prompt: str, *, model: str, timeout: int) -> dict:
    """Call Gemini and return the parsed result. Stub owned by ws-g."""
    raise NotImplementedError("generate is implemented by ws-g-gemini-llm")
