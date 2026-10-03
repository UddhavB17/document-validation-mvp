"""The model evaluation writes fixtures only to its disposable local state."""

import importlib.util
import json
import os
import sys
from pathlib import Path


def test_evaluation_overrides_inherited_database_and_store(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[1] / "scripts" / "eval_gemini_models.py"
    spec = importlib.util.spec_from_file_location("eval_gemini_models", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/never-connect")
    monkeypatch.setenv("DMEF_STORAGE_BACKEND", "gcs")
    (tmp_path / "gold.json").write_text(json.dumps({"cases": [{"file": "test.pdf"}]}))
    monkeypatch.setattr(module.tempfile, "mkdtemp", lambda **kwargs: str(tmp_path / "work"))

    def run_case(model, case, fixtures_dir, work_root):
        assert os.environ["DATABASE_URL"] == ""
        assert Path(os.environ["DATABASE_PATH"]) == work_root / "eval.db"
        assert os.environ["DMEF_STORAGE_BACKEND"] == "local"
        assert Path(os.environ["DMEF_LOCAL_STORE_DIR"]) == work_root / "store"
        assert Path(os.environ["PAGE_OUTPUT_DIR"]) == work_root / "processed"
        assert Path(os.environ["REPORT_OUTPUT_DIR"]) == work_root / "reports"
        return dict(
            model=model,
            file=case["file"],
            accuracy=1,
            false_positives=0,
            seconds=0,
            tokens_in=0,
            tokens_out=0,
            usd=0,
            calls=0,
            notes="",
        )

    monkeypatch.setattr(module, "run_case", run_case)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script),
            "--models",
            "synthetic",
            "--fixtures",
            str(tmp_path),
            "--out",
            str(tmp_path / "out.csv"),
        ],
    )
    assert module.main() == 0
    assert "synthetic,test.pdf" in (tmp_path / "out.csv").read_text()
