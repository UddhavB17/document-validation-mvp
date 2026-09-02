"""Local development health checks for DMEF."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from services.llm_client import has_api_key_configured, llm_endpoint_label, llm_model, llm_provider
from services.paths import (
    checklist_json_path,
    database_path,
    processed_output_dir,
    report_output_dir,
    upload_dir,
)
from services.python_runtime import REQUIRED_MAJOR, REQUIRED_MINOR

load_dotenv()


@dataclass(frozen=True)
class HealthItem:
    name: str
    status: str
    detail: str
    required: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "required": self.required,
        }


def collect_local_health(*, check_ollama: bool = True) -> dict[str, Any]:
    """Return local setup health details without importing heavy OCR modules."""
    items = [
        _python_item(),
        _module_item("PyMuPDF", "fitz"),
        _module_item("Google Cloud Vision", "google.cloud.vision"),
        _path_item("Database path", database_path(), must_exist=False, parent_required=True),
        _path_item("Upload folder", upload_dir(), must_exist=False, parent_required=False),
        _path_item(
            "Page output folder", processed_output_dir(), must_exist=False, parent_required=False
        ),
        _path_item(
            "Report output folder", report_output_dir(), must_exist=False, parent_required=False
        ),
        _path_item("Checklist JSON", checklist_json_path(), must_exist=True, parent_required=True),
        _llm_config_item(),
    ]
    if check_ollama and llm_provider() == "ollama":
        items.append(_ollama_connection_item())
    elif check_ollama and llm_provider() not in {"ollama", "none"}:
        items.append(_api_key_item())

    status = "ok"
    if any(item.required and item.status == "error" for item in items):
        status = "error"
    elif any(item.status == "warning" for item in items):
        status = "warning"

    return {
        "status": status,
        "items": [item.as_dict() for item in items],
        "paths": {
            "database": str(database_path()),
            "upload_dir": str(upload_dir()),
            "page_output_dir": str(processed_output_dir()),
            "report_output_dir": str(report_output_dir()),
            "checklist_json": str(checklist_json_path()),
        },
        "llm": {
            "provider": llm_provider(),
            "endpoint": llm_endpoint_label(),
            "model": llm_model(),
        },
    }


def has_required_errors(health: dict[str, Any]) -> bool:
    return any(
        bool(item.get("required")) and item.get("status") == "error"
        for item in health.get("items", [])
        if isinstance(item, dict)
    )


def _python_item() -> HealthItem:
    version = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info[:2] != (REQUIRED_MAJOR, REQUIRED_MINOR):
        return HealthItem(
            "Python",
            "error",
            f"Found {version}; DMEF requires Python {REQUIRED_MAJOR}.{REQUIRED_MINOR}.x.",
        )
    return HealthItem("Python", "ok", version)


def _module_item(label: str, module_name: str) -> HealthItem:
    if importlib.util.find_spec(module_name) is None:
        return HealthItem(label, "error", f"Missing Python package/module: {module_name}")
    return HealthItem(label, "ok", f"Module `{module_name}` is importable.")


def _path_item(
    label: str,
    path: Path,
    *,
    must_exist: bool,
    parent_required: bool,
) -> HealthItem:
    resolved = path.resolve()
    if must_exist and not resolved.exists():
        return HealthItem(label, "error", f"Missing: {resolved}")
    if parent_required and not resolved.parent.exists():
        return HealthItem(
            label, "warning", f"Parent folder will be created: {resolved.parent}", required=False
        )
    if not resolved.exists():
        return HealthItem(
            label, "warning", f"Will be created when needed: {resolved}", required=False
        )
    return HealthItem(label, "ok", str(resolved), required=False)


def _llm_config_item() -> HealthItem:
    return HealthItem(
        "LLM config",
        "ok",
        f"provider={llm_provider()} | endpoint={llm_endpoint_label()} | model={llm_model()}",
        required=False,
    )


def _api_key_item() -> HealthItem:
    if has_api_key_configured():
        return HealthItem("LLM API key", "ok", "API key is configured.", required=False)
    return HealthItem(
        "LLM API key", "warning", "LLM_API_KEY or OPENAI_API_KEY is empty.", required=False
    )


def _ollama_connection_item() -> HealthItem:
    base_url = _ollama_base_url()
    model = _ollama_model()
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return HealthItem(
            "Ollama connection", "warning", f"Unavailable at {base_url}: {exc}", required=False
        )

    models = payload.get("models") if isinstance(payload, dict) else []
    names = {
        str(item.get("name") or item.get("model") or "")
        for item in models
        if isinstance(item, dict)
    }
    if model and names and model not in names:
        return HealthItem(
            "Ollama model",
            "warning",
            f"Ollama is running, but `{model}` was not listed by /api/tags.",
            required=False,
        )
    return HealthItem("Ollama connection", "ok", f"Available at {base_url}", required=False)


def _ollama_base_url() -> str:
    raw = (
        os.getenv("LOCAL_OLLAMA_CLASSIFIER_URL")
        or os.getenv("LOCAL_LLM_API_URL")
        or "http://localhost:11434"
    )
    return _normalize_ollama_base_url(raw)


def _ollama_model() -> str:
    return (
        os.getenv("OLLAMA_CLASSIFIER_MODEL")
        or os.getenv("LOCAL_LLM_MODEL")
        or os.getenv("LLM_FIELD_VERIFIER_MODEL")
        or "qwen2.5:7b"
    )


def _normalize_ollama_base_url(url: str) -> str:
    cleaned = str(url or "").strip().rstrip("/")
    if cleaned.endswith("/api/generate"):
        return cleaned[: -len("/api/generate")]
    return cleaned or "http://localhost:11434"


def _print_health(health: dict[str, Any]) -> None:
    print(f"DMEF local health: {health['status'].upper()}")
    for item in health["items"]:
        marker = {"ok": "OK", "warning": "WARN", "error": "ERROR"}.get(
            item["status"], item["status"].upper()
        )
        print(f"[{marker}] {item['name']}: {item['detail']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local DMEF development setup.")
    parser.add_argument("--no-ollama", action="store_true", help="Skip Ollama connection check.")
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Return a non-zero exit code for required errors.",
    )
    args = parser.parse_args()

    health = collect_local_health(check_ollama=not args.no_ollama)
    _print_health(health)
    if args.fail_on_error and has_required_errors(health):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
