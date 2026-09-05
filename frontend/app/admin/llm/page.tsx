"use client";

import { useQuery } from "@tanstack/react-query";

import { ErrorMessage, InfoMessage, LoadingMessage } from "@/components/Message";
import { PageHeader } from "@/components/PageHeader";
import { api } from "@/lib/api";

const LLM_KEYS = ["llm_enabled", "llm_provider", "llm_model"];

/**
 * Admin LLM overview. Provider settings come from the existing settings
 * endpoint. Per-call token and cost accounting lives behind the ws-g cost
 * endpoint (routes/llm_settings.py), which is not in this branch yet, so the
 * cost section names that gap instead of guessing the shape.
 */
export default function AdminLlmPage() {
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });

  const llmSettings = (settings.data ?? []).filter((item) => LLM_KEYS.includes(item.config_key));

  return (
    <div className="mx-auto max-w-[1100px] space-y-6">
      <PageHeader title="LLM" description="Language-model provider settings and usage cost." />

      {settings.isLoading ? <LoadingMessage message="Loading model settings…" /> : null}
      {settings.isError ? <ErrorMessage message="Could not load model settings. Refresh to try again." /> : null}

      {settings.data ? (
        <section aria-labelledby="admin-llm-settings" className="rounded-xl border border-[#E1E5EB] bg-white p-5 shadow-sm">
          <h2 id="admin-llm-settings" className="text-base font-bold text-slate-900">Provider</h2>
          <dl className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
            {llmSettings.map((item) => (
              <div key={item.config_key} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                <dt className="text-[11px] font-bold uppercase tracking-wider text-slate-500">{item.label || item.config_key}</dt>
                <dd className="mt-1 break-words font-mono text-sm font-bold text-slate-900">
                  {item.is_secret ? (item.has_value ? "Configured" : "Not set") : item.config_value || "—"}
                </dd>
              </div>
            ))}
          </dl>
          <p className="mt-3 text-xs font-medium text-slate-500">
            Change these values under Settings. Only non-secret values are shown here.
          </p>
        </section>
      ) : null}

      <section aria-labelledby="admin-llm-cost" className="rounded-xl border border-[#E1E5EB] bg-white p-5 shadow-sm">
        <h2 id="admin-llm-cost" className="text-base font-bold text-slate-900">Cost summary</h2>
        <InfoMessage message="Per-call token and cost totals will appear here once the ws-g cost endpoint (routes/llm_settings.py) lands. See NEEDS-COORDINATION in the ws-e commit." />
      </section>
    </div>
  );
}
