"use client";

import { useEffect, useState } from "react";

import { llmApi, LlmProviders } from "@/lib/api";
import { SettingsComponentProps } from "./types";

const PROVIDER_LABELS: Record<string, string> = {
  ollama: "Ollama (Local)",
  openai: "OpenAI",
  openai_compatible: "OpenAI-compatible",
  gemini: "Gemini",
  none: "None (disabled)",
};

export function LlmSettings({ getValue, draftValues, setDraftValue, updateSetting }: SettingsComponentProps) {
  const isLlmEnabled = getValue("llm_enabled") === "true";
  const provider = getValue("llm_provider");
  const model = draftValues["llm_model"] ?? getValue("llm_model");
  const [providersData, setProvidersData] = useState<LlmProviders | null>(null);

  useEffect(() => {
    let active = true;
    llmApi.providers()
      .then((data) => {
        if (active) setProvidersData(data);
      })
      .catch(() => {
        if (active) setProvidersData(null);
      });
    return () => {
      active = false;
    };
  }, []);

  const providers = providersData?.providers ?? ["ollama", "openai", "openai_compatible", "gemini", "none"];
  const geminiModels = providersData?.gemini_models ?? [];
  const costs = providersData?.costs ?? [];
  const isGemini = provider === "gemini";

  return (
    <div className="rounded-xl border border-[#E1E5EB] bg-white p-6 shadow-2xs">
      <h2 className="mb-4 text-base font-bold font-serif text-[#16202E] flex items-center gap-2 border-b border-slate-50 pb-2">🤖 LLM Verification Settings</h2>
      <div className="space-y-6">
        <div className="flex items-start justify-between">
          <div>
            <label className="text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] block">Enable LLM Verification checks</label>
            <span className="text-xs text-[#5C6B7A] block mt-1 font-semibold leading-relaxed">Toggle dynamic validation checks &amp; checklist evaluations via LLM.</span>
          </div>
          <button type="button" onClick={() => updateSetting("llm_enabled", isLlmEnabled ? "false" : "true")} className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${isLlmEnabled ? "bg-[#2B4C7E]" : "bg-slate-200"}`}>
            <span className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${isLlmEnabled ? "translate-x-5" : "translate-x-0"}`} />
          </button>
        </div>

        {isLlmEnabled ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-4 border-t border-slate-100">
            <div>
              <label className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">LLM Provider</label>
              <select value={provider} onChange={(event) => updateSetting("llm_provider", event.target.value)} className="mt-1 block w-full rounded-lg border border-[#E1E5EB] bg-white px-3.5 py-2.5 text-sm text-[#16202E] focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs cursor-pointer font-medium">
                {providers.map((item) => (
                  <option key={item} value={item}>{PROVIDER_LABELS[item] ?? item}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">Model Name</label>
              {isGemini && geminiModels.length > 0 ? (
                <select value={geminiModels.includes(model) ? model : ""} onChange={(event) => updateSetting("llm_model", event.target.value)} className="mt-1 block w-full rounded-lg border border-[#E1E5EB] bg-white px-3.5 py-2.5 text-sm text-[#16202E] focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs cursor-pointer font-medium">
                  <option value="" disabled>Select a Gemini model</option>
                  {geminiModels.map((item) => (
                    <option key={item} value={item}>{item}</option>
                  ))}
                </select>
              ) : (
                <input type="text" value={model} onChange={(event) => setDraftValue("llm_model", event.target.value)} onBlur={() => updateSetting("llm_model", model)} placeholder="e.g. qwen2.5:7b-instruct-q4_0" className="mt-1 block w-full rounded-lg border border-[#E1E5EB] bg-white px-3.5 py-2.5 text-sm text-[#16202E] focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs font-medium" />
              )}
              <span className="text-[10px] text-[#5C6B7A] font-semibold mt-1 block">Press enter or focus out to save</span>
            </div>
          </div>
        ) : null}

        {costs.length > 0 ? (
          <div className="pt-4 border-t border-slate-100">
            <span className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">LLM usage &amp; cost</span>
            <ul className="text-xs text-[#5C6B7A] font-medium space-y-1">
              {costs.map((row) => (
                <li key={row.model}>
                  {row.model}: {row.calls} calls, {row.tokens_in + row.tokens_out} tokens, ${row.usd.toFixed(4)}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </div>
  );
}
