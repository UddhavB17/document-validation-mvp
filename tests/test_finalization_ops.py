"""Finalization persists the ops payload (fx-integrate-df).

``_finalize_pipeline_result`` must invoke ``store_ops_payload`` so
``applications.ops_findings_json`` is non-null after a run (the endpoint
recomputes when needed). Heavy pipeline collaborators are stubbed; the
store call itself is the assertion (mock OK per the brief).
"""

from __future__ import annotations

import services.ops_presentation as ops_presentation
import services.pipeline.finalization as finalization


def test_finalize_stores_ops_payload(monkeypatch, tmp_path) -> None:
    calls: list[int] = []
    monkeypatch.setattr(finalization, "_save_pages", lambda *a, **k: None)
    monkeypatch.setattr(
        finalization,
        "aggregate",
        lambda *a, **k: {"anomalies": [], "total_pages": 0, "final_status": "clean"},
    )
    monkeypatch.setattr(finalization, "summarize_exceptions", lambda *a, **k: "")
    monkeypatch.setattr(finalization, "generate_summaries", lambda *a, **k: None)
    monkeypatch.setattr(finalization, "_should_call_llm", lambda *a, **k: False)
    monkeypatch.setattr(finalization, "build_report", lambda *a, **k: {})
    monkeypatch.setattr(
        finalization, "save_report_json", lambda *a, **k: tmp_path / "r.json"
    )
    monkeypatch.setattr(finalization, "mark_completed", lambda *a, **k: None)
    monkeypatch.setattr(finalization, "log_action", lambda *a, **k: None)
    # finalization imports store_ops_payload lazily, so patching the source
    # module attribute is observed by the call under test.
    monkeypatch.setattr(
        ops_presentation,
        "store_ops_payload",
        lambda application_id: calls.append(application_id) or {"top_findings": []},
    )

    finalization._finalize_pipeline_result(
        application_id=1,
        pages=[],
        ground_truth={},
        anomalies=[],
        pipeline_status="completed",
        partial_failure_count=0,
        generate_llm_summary=False,
    )
    assert calls == [1]
