"""Container-context hygiene: local secrets and checkouts stay out of the image.

Never reads real secret values; only inspects ``.dockerignore`` patterns and
the ``Dockerfile`` build context directive.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _dockerignore_lines() -> list[str]:
    text = (REPO_ROOT / ".dockerignore").read_text()
    return [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]


def test_env_files_excluded_but_example_allowed() -> None:
    lines = _dockerignore_lines()
    assert ".env" in lines
    assert any(line == ".env.*" or line.endswith("/.env.*") for line in lines)
    assert "!.env.example" in lines or "!**/.env.example" in lines
    # The negation must come after the wildcard exclusion to take effect.
    joined = "\n".join(lines)
    assert joined.index(".env.*") < joined.index("!.env.example") or joined.index(".env.*") < joined.index(
        "!**/.env.example"
    )
    assert (REPO_ROOT / ".env.example").exists()


def test_worktrees_and_agent_config_excluded() -> None:
    joined = "\n".join(_dockerignore_lines())
    assert ".worktrees/" in joined
    assert ".opencode/" in joined


def test_credential_key_artifacts_excluded() -> None:
    joined = "\n".join(_dockerignore_lines())
    assert "*.pem" in joined
    assert "*.key" in joined
    assert "*.p12" in joined or "*.pfx" in joined


def test_docker_build_context_still_uses_copy_dot() -> None:
    # Hygiene matters precisely because the Dockerfile copies the context.
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()
    assert "COPY . ." in dockerfile


def test_runtime_rules_are_included_after_excluding_local_data() -> None:
    lines = _dockerignore_lines()
    assert "data/" not in lines
    excluded_at = lines.index("data/*")
    for filename in ("checklist.json", "document_type_registry.json", "stamp_duty_rules.json"):
        assert lines.index(f"!data/{filename}") > excluded_at
        assert (REPO_ROOT / "data" / filename).is_file()
