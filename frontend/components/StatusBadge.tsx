export function StatusBadge({ status, uppercase = true }: { status: string; uppercase?: boolean }) {
  const norm = (status || "").toLowerCase().trim();

  const labelMap: Record<string, string> = {
    clean: "Clean",
    verified: "Verified",
    verified_with_override: "Verified with override",
    found: "Found",
    prepared: "Prepared",
    match: "Match",
    success: "Success",
    accepted: "Accepted",
    critical: "Critical",
    pipeline_failed: "Pipeline failed",
    incomplete: "Incomplete",
    missing: "Missing",
    failed: "Failed",
    mismatch: "Mismatch",
    stale: "Stale",
    flagged: "Flagged",
    needs_review: "Needs review",
    processing: "Processing",
    ocr_completed: "OCR completed",
    queued: "Queued",
    preparing: "Preparing",
    attention: "Attention",
    review: "Review",
    request_docs: "Request documents",
    sent_back: "Sent back",
    overridden: "Overridden",
    override: "Override",
    ok: "Online",
    info: "Info",
  };
  const label = labelMap[norm] ?? (status ? status.replace(/_/g, " ") : "Unknown");
  const tone = getTone(norm);

  return (
    <span className={`status-badge status-badge--${tone}`}>
      <span className="status-badge__dot" aria-hidden="true" />
      <span>{uppercase ? label.toUpperCase() : label}</span>
    </span>
  );
}

function getTone(status: string): "success" | "warning" | "danger" | "info" | "neutral" {
  if (["clean", "verified", "verified_with_override", "found", "prepared", "match", "success", "accepted", "ok"].includes(status)) {
    return "success";
  }
  if (["critical", "pipeline_failed", "incomplete", "missing", "failed", "mismatch", "stale", "flagged", "request_docs", "sent_back"].includes(status)) {
    return "danger";
  }
  if (["needs_review", "processing", "ocr_completed", "queued", "preparing", "attention", "review", "overridden", "override"].includes(status)) {
    return "warning";
  }
  if (["info", "pending", "running"].includes(status)) {
    return "info";
  }
  return "neutral";
}
