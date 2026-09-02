import { ZipPreparationProgress } from "@/lib/api";

export function ZipPreparationProgressPanel({ progress }: { progress: ZipPreparationProgress }) {
  return (
    <div className="rounded-xl border border-[#E1E5EB] bg-[#F6F7FA] p-5 space-y-3 shadow-inner">
      <div className="flex items-center justify-between text-xs font-bold text-[#5C6B7A] uppercase tracking-wider">
        <span>Stage: {progress.stage || "Initializing"}</span>
        <span className="text-[#2B4C7E] font-mono">
          {progress.processed_files || 0} / {progress.total_files || 0} files
        </span>
      </div>
      <div className="text-sm font-semibold text-slate-800">{progress.message || "Starting ZIP extraction..."}</div>
      {(progress.total_files ?? 0) > 0 ? (
        <div className="w-full bg-slate-200 border border-slate-350 rounded-full h-2.5 overflow-hidden shadow-inner">
          <div
            className="bg-[#2B4C7E] h-full rounded-full transition-all duration-300"
            style={{
              width: `${Math.round(((progress.processed_files || 0) / (progress.total_files || 1)) * 100)}%`,
            }}
          />
        </div>
      ) : null}
    </div>
  );
}
