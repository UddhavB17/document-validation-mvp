"""Shared HTTP client for local/open-source LLM APIs (Ollama-style)."""

from __future__ import annotations

import os

import requests


def call_llm_api(prompt: str, *, max_tokens: int = 450, timeout: int = 90) -> str | None:
    """Send a prompt to the configured local LLM endpoint."""
    api_url = (
        os.getenv("LLM_API_URL")
        or os.getenv("LOCAL_LLM_API_URL")
        or os.getenv("OPEN_SOURCE_LLM_API_URL")
        or "http://localhost:11434/api/generate"
    )
    model = os.getenv("LOCAL_LLM_MODEL") or os.getenv("LLM_MODEL") or "llama3.1"

    if "11434" in api_url or api_url.endswith("/api/generate"):
        payload = {"model": model, "prompt": prompt, "stream": False}
    else:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        }

    response = requests.post(api_url, json=payload, timeout=timeout)
    response.raise_for_status()
    return extract_response_text(response.json())


def extract_response_text(payload: dict) -> str | None:
    if payload.get("response"):
        return payload["response"]
    if payload.get("text"):
        return payload["text"]
    if payload.get("output"):
        return payload["output"]

    choices = payload.get("choices") or []
    if choices:
        first_choice = choices[0]
        message = first_choice.get("message") or {}
        return message.get("content") or first_choice.get("text")

    return None
