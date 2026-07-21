export function StatusBadge({ status }: { status: string }) {
  let colors = "bg-slate-50 text-slate-700 border-slate-200";
  
  if (["CLEAN", "verified", "verified_with_override", "FOUND", "prepared"].includes(status)) {
    colors = "bg-emerald-50 text-emerald-700 border-emerald-200/80 shadow-sm shadow-emerald-100/50";
  } else if (["CRITICAL", "pipeline_failed", "incomplete", "MISSING", "failed"].includes(status)) {
    colors = "bg-red-50 text-red-700 border-red-200/80 shadow-sm shadow-red-100/50";
  } else if (["NEEDS_REVIEW", "processing", "ocr_completed", "queued", "preparing"].includes(status)) {
    colors = "bg-amber-50 text-amber-800 border-amber-200/80 shadow-sm shadow-amber-100/50";
  }
  
  return (
    <span className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold tracking-wider uppercase border ${colors}`}>
      <span className={`h-1.5 w-1.5 rounded-full mr-2 ${
        status === "processing" || status === "preparing" ? "bg-amber-550 animate-ping" : 
        ["CLEAN", "verified", "verified_with_override", "FOUND", "prepared"].includes(status) ? "bg-emerald-500" :
        ["CRITICAL", "pipeline_failed", "incomplete", "MISSING", "failed"].includes(status) ? "bg-red-500" : "bg-amber-500"
      }`}></span>
      {status.replace(/_/g, " ")}
    </span>
  );
}
