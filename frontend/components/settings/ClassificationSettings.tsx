"use client";

import { SettingsComponentProps } from "./types";

export function ClassificationSettings({ getValue, updateSetting }: SettingsComponentProps) {
  const minConfidence = parseFloat(getValue("min_confidence") || "0.70");
  const nameFuzzyThreshold = parseFloat(getValue("validation.name_fuzzy_threshold") || "85.0");
  const amountTolerance = parseFloat(getValue("validation.amount_tolerance_percent") || "1.0");
  const dateTolerance = parseInt(getValue("validation.date_tolerance_days") || "0", 10);

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="rounded-xl border border-[#E1E5EB] bg-white p-6 shadow-2xs">
        <h2 className="mb-4 text-base font-bold font-serif text-[#16202E] flex items-center gap-2 border-b border-slate-50 pb-2">
          📄 Classification Confidence
        </h2>
        <div>
          <label className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-1">
            Minimum Classification Confidence
          </label>
          <p className="text-xs text-[#5C6B7A] mb-3 font-semibold leading-relaxed">
            Minimum score required to automatically classify document pages. Default: 0.70.
          </p>
          <div className="flex items-center gap-4">
            <input
              type="range"
              min="0.4"
              max="0.95"
              step="0.05"
              value={minConfidence}
              onChange={(event) => updateSetting("min_confidence", event.target.value)}
              className="h-2 w-64 cursor-pointer appearance-none rounded-lg bg-slate-200 accent-[#2B4C7E]"
            />
            <span className="text-sm font-bold font-mono text-[#16202E]">{minConfidence.toFixed(2)}</span>
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-[#E1E5EB] bg-white p-6 shadow-2xs">
        <h2 className="mb-4 text-base font-bold font-serif text-[#16202E] flex items-center gap-2 border-b border-slate-50 pb-2">
          🔍 Field Verification &amp; Matching Tolerances
        </h2>
        <div className="space-y-6">
          <div>
            <label className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-1">
              Fuzzy Name Match Threshold (%)
            </label>
            <p className="text-xs text-[#5C6B7A] mb-3 font-semibold leading-relaxed">
              Minimum similarity score for person names across documents (Aadhaar, PAN, Loan Agreement). Default: 85%.
            </p>
            <div className="flex items-center gap-4">
              <input
                type="range"
                min="50"
                max="100"
                step="1"
                value={nameFuzzyThreshold}
                onChange={(event) => updateSetting("validation.name_fuzzy_threshold", event.target.value)}
                className="h-2 w-64 cursor-pointer appearance-none rounded-lg bg-slate-200 accent-[#2B4C7E]"
              />
              <span className="text-sm font-bold font-mono text-[#16202E]">{nameFuzzyThreshold}%</span>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-4 border-t border-slate-100">
            <div>
              <label className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-1">
                Amount Difference Tolerance (%)
              </label>
              <p className="text-xs text-[#5C6B7A] mb-2 font-semibold leading-relaxed">
                Allowable numeric variance when verifying loan amounts across sanction letters and agreements.
              </p>
              <div className="flex items-center gap-3">
                <input
                  type="number"
                  min="0"
                  max="10"
                  step="0.1"
                  value={amountTolerance}
                  onChange={(event) => updateSetting("validation.amount_tolerance_percent", event.target.value)}
                  className="block w-32 rounded-lg border border-[#E1E5EB] bg-white px-3 py-2 text-sm font-mono text-[#16202E] focus:border-[#2B4C7E] focus:outline-none"
                />
                <span className="text-xs text-[#5C6B7A] font-semibold">% variance</span>
              </div>
            </div>

            <div>
              <label className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-1">
                Date Discrepancy Tolerance (Days)
              </label>
              <p className="text-xs text-[#5C6B7A] mb-2 font-semibold leading-relaxed">
                Allowable discrepancy in days when comparing dates across documents. Default: 0 (exact match).
              </p>
              <div className="flex items-center gap-3">
                <input
                  type="number"
                  min="0"
                  max="30"
                  step="1"
                  value={dateTolerance}
                  onChange={(event) => updateSetting("validation.date_tolerance_days", event.target.value)}
                  className="block w-32 rounded-lg border border-[#E1E5EB] bg-white px-3 py-2 text-sm font-mono text-[#16202E] focus:border-[#2B4C7E] focus:outline-none"
                />
                <span className="text-xs text-[#5C6B7A] font-semibold">days</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
