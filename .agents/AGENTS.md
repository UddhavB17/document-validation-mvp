# Project-Scoped Agent Rules

## LLM Prompts and Formats
- **Always use TOON (Token-Oriented Object Notation) for LLM communications**: When prompting LLMs for structured data or when LLMs are generating structured output, use TOON format instead of JSON or XML to optimize token efficiency and minimize API costs.
- Parse generated TOON strings using the `python-toon` library (`toon.decode`).
