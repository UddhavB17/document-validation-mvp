export function StatusBadge({ status, uppercase = true }: { status: string; uppercase?: boolean }) {
  const norm = (status || "").toLowerCase().trim();
  
  let label = status ? status.replace(/_/g, " ") : "";
  let tone = "attention"; // default
  
  if (["clean", "verified", "verified_with_override", "found", "prepared", "match", "success"].includes(norm)) {
    tone = "match";
    label = norm === "clean" ? "Clean" : (norm === "verified" ? "Verified" : (norm === "match" ? "Match" : label));
  } else if (["critical", "pipeline_failed", "incomplete", "missing", "failed", "mismatch", "stale", "flagged"].includes(norm)) {
    tone = "mismatch";
    label = norm === "critical" ? "Critical" : (norm === "mismatch" ? "Mismatch" : label);
  } else if (["needs_review", "processing", "ocr_completed", "queued", "preparing", "attention", "review"].includes(norm)) {
    tone = "attention";
    label = norm === "needs_review" ? "Needs Review" : (norm === "attention" ? "Attention" : label);
  }
  
  return (
    <span className={`stamp ${tone} select-none`}>
      {uppercase ? label.toUpperCase() : label}
    </span>
  );
}
