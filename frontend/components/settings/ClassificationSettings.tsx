export function ClassificationSettings({
  minConfidence,
  onConfidenceChange,
}: {
  minConfidence: number;
  onConfidenceChange: (value: string) => void;
}) {
  return (
    <div className="rounded-xl border border-[#E1E5EB] bg-white p-6 shadow-2xs">
      <h2 className="mb-4 text-base font-bold font-serif text-[#16202E] flex items-center gap-2 border-b border-slate-50 pb-2">
        ⚙️ Classification Settings
      </h2>
      <div className="space-y-6">
        <div>
          <label className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-1">
            Minimum Classification Confidence
          </label>
          <p className="text-xs text-[#5C6B7A] mb-3 font-semibold leading-relaxed">
            Raise or lower the minimum score required to auto-classify pages. Currently recommended: 0.70.
          </p>
          <div className="flex items-center gap-4">
            <input
              type="range"
              min="0.4"
              max="0.95"
              step="0.05"
              value={minConfidence}
              onChange={(e) => onConfidenceChange(e.target.value)}
              className="h-2 w-64 cursor-pointer appearance-none rounded-lg bg-slate-200 accent-[#2B4C7E]"
            />
            <span className="text-sm font-bold font-mono text-[#16202E]">{minConfidence}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
