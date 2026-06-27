"""LLM summary boundary."""


def summarize_exceptions(exceptions: list[dict]) -> str:
    if not exceptions:
        return "No exceptions found."
    return f"{len(exceptions)} exception(s) require review."
