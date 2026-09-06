# Project-Scoped Agent Rules

## LLM Prompts and Formats
- **TOON for prompt input, JSON for model output**: When prompting LLMs, encode the input payload with TOON (Token-Oriented Object Notation) via `toon.encode` to optimize token efficiency. Instruct the model to answer in JSON only, and parse every response with `json.loads` plus a schema check.
- Parse legacy TOON model output with the `python-toon` library (`toon.decode`) only as a fallback for older local models.
- Env only via `services/config.py` helpers or `services/paths.py` — no new `os.getenv` in domain modules.
