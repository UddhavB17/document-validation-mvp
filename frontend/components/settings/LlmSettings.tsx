import { SettingsContext } from "@/components/settings/SettingsControls";

export function LlmSettings({ ctx }: { ctx: SettingsContext }) {
  const { getVal, updateSingleSetting } = ctx;
  const isLlmEnabled = getVal("llm_enabled") === "true";
  const provider = getVal("llm_provider");
  const model = getVal("llm_model");

  return (
    <div className="rounded-xl border border-[#E1E5EB] bg-white p-6 shadow-2xs">
      <h2 className="mb-4 text-base font-bold font-serif text-[#16202E] flex items-center gap-2 border-b border-slate-50 pb-2">
        🤖 LLM Verification Settings
      </h2>
      <div className="space-y-6">
        <div className="flex items-start justify-between">
          <div>
            <label className="text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] block">
              Enable LLM Verification checks
            </label>
            <span className="text-xs text-[#5C6B7A] block mt-1 font-semibold leading-relaxed">
              Toggle dynamic validation checks & checklist evaluations via LLM.
            </span>
          </div>
          <button
            type="button"
            onClick={() => updateSingleSetting("llm_enabled", isLlmEnabled ? "false" : "true")}
            className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
              isLlmEnabled ? "bg-[#2B4C7E]" : "bg-slate-200"
            }`}
          >
            <span
              className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                isLlmEnabled ? "translate-x-5" : "translate-x-0"
              }`}
            />
          </button>
        </div>

        {isLlmEnabled ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-4 border-t border-slate-100">
            <div>
              <label className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">LLM Provider</label>
              <select
                value={provider}
                onChange={(e) => updateSingleSetting("llm_provider", e.target.value)}
                className="mt-1 block w-full rounded-lg border border-[#E1E5EB] bg-white px-3.5 py-2.5 text-sm text-[#16202E] focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs cursor-pointer font-medium"
              >
                <option value="ollama">Ollama (Local)</option>
                <option value="openai">OpenAI</option>
                <option value="gemini">Gemini</option>
              </select>
            </div>
            <div>
              <label className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">Model Name</label>
              <input
                type="text"
                value={model}
                onChange={() => {}}
                onBlur={(e) => updateSingleSetting("llm_model", e.target.value)}
                placeholder="e.g. qwen2.5:7b-instruct-q4_0"
                className="mt-1 block w-full rounded-lg border border-[#E1E5EB] bg-white px-3.5 py-2.5 text-sm text-[#16202E] focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs font-medium"
              />
              <span className="text-[10px] text-[#5C6B7A] font-semibold mt-1 block">Press enter or focus out to save</span>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
