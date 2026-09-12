import { ZipPreparationProgress as ZipProgress } from "@/lib/api";

export function ZipPreparationProgress({ progress }: { progress: ZipProgress }) {
  const processedFiles = progress.processed_files ?? 0;
  const totalFiles = progress.total_files ?? 0;
  const percentage = totalFiles > 0 ? Math.min(100, Math.round((processedFiles / totalFiles) * 100)) : 0;

  return (
    <div className="rounded-xl border border-[#E1E5EB] bg-[#F6F7FA] p-5 space-y-3 shadow-inner" role="status" aria-live="polite">
      <div className="flex items-center justify-between text-xs font-bold text-[#5C6B7A] uppercase tracking-wider">
        <span>Stage: {progress.stage || "Initializing"}</span>
        <span className="text-[#2B4C7E] font-mono">{processedFiles} / {totalFiles} files</span>
      </div>
      <div className="text-sm font-semibold text-slate-800">{progress.message || "Starting ZIP extraction..."}</div>
      {totalFiles > 0 ? (
        <div
          className="w-full bg-slate-200 border border-slate-350 rounded-full h-2.5 overflow-hidden shadow-inner"
          role="progressbar"
          aria-label="ZIP preparation progress"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percentage}
        >
          <div className="bg-[#2B4C7E] h-full rounded-full transition-all duration-300" style={{ width: `${percentage}%` }} />
        </div>
      ) : null}
    </div>
  );
}
