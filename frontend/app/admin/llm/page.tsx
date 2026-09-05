"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ErrorMessage, InfoMessage, LoadingMessage } from "@/components/Message";
import { PageHeader } from "@/components/PageHeader";
import { api, llmApi } from "@/lib/api";

const LLM_KEYS = ["llm_enabled", "llm_provider", "llm_model"];

/**
 * Admin LLM overview. The provider dropdown and the cost summary come from
 * GET /settings/llm/providers via the shared helper. When that endpoint is
 * unavailable the page shows a quiet empty state.
 */
export default function AdminLlmPage() {
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const providers = useQuery({ queryKey: ["llmProviders"], queryFn: llmApi.providers, retry: false });
  const updateProvider = useMutation({
    mutationFn: (value: string) => api.updateSetting("llm_provider", value),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["llmProviders"] }),
        queryClient.invalidateQueries({ queryKey: ["settings"] }),
      ]);
    },
  });

  const llmSettings = (settings.data ?? []).filter((item) => LLM_KEYS.includes(item.config_key));
  const providerList = providers.data?.providers ?? [];
  const currentProvider = providers.data?.current_provider ?? "";
  const providerOptions =
    currentProvider && !providerList.includes(currentProvider)
      ? [currentProvider, ...providerList]
      : providerList;
  const costs = providers.data?.costs ?? [];

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

      <section aria-labelledby="admin-llm-providers" className="rounded-xl border border-[#E1E5EB] bg-white p-5 shadow-sm">
        <h2 id="admin-llm-providers" className="text-base font-bold text-slate-900">Available providers</h2>
        {providers.isLoading ? <LoadingMessage message="Loading providers…" /> : null}
        {providers.isError ? (
          <InfoMessage message="Provider list is currently unavailable." />
        ) : null}
        {providers.data ? (
          <div className="mt-3 space-y-3">
            <label className="block max-w-sm">
              <span className="text-[11px] font-bold uppercase tracking-wider text-slate-500">Active provider</span>
              <select
                value={currentProvider}
                disabled={updateProvider.isPending}
                onChange={(event) => updateProvider.mutate(event.target.value)}
                className="mt-1 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 font-mono text-sm font-bold text-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-primary"
              >
                {providerOptions.map((provider) => (
                  <option key={provider} value={provider}>
                    {provider}
                  </option>
                ))}
              </select>
            </label>
            {updateProvider.isError ? (
              <ErrorMessage message="Could not switch provider. Refresh to try again." />
            ) : null}
            <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                <dt className="text-[11px] font-bold uppercase tracking-wider text-slate-500">Current model</dt>
                <dd className="mt-1 break-words font-mono text-sm font-bold text-slate-900">
                  {providers.data.current_model || "—"}
                </dd>
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                <dt className="text-[11px] font-bold uppercase tracking-wider text-slate-500">Gemini models</dt>
                <dd className="mt-1 break-words font-mono text-sm font-bold text-slate-900">
                  {providers.data.gemini_models.length > 0 ? providers.data.gemini_models.join(", ") : "—"}
                </dd>
              </div>
            </dl>
          </div>
        ) : null}
      </section>

      <section aria-labelledby="admin-llm-cost" className="rounded-xl border border-[#E1E5EB] bg-white p-5 shadow-sm">
        <h2 id="admin-llm-cost" className="text-base font-bold text-slate-900">Cost summary</h2>
        {providers.data ? (
          costs.length === 0 ? (
            <InfoMessage message="No usage recorded yet." />
          ) : (
            <div className="mt-3 overflow-x-auto">
              <table className="min-w-full border-collapse text-left text-sm">
                <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th scope="col" className="px-3 py-2.5">Model</th>
                    <th scope="col" className="px-3 py-2.5">Calls</th>
                    <th scope="col" className="px-3 py-2.5">Tokens in</th>
                    <th scope="col" className="px-3 py-2.5">Tokens out</th>
                    <th scope="col" className="px-3 py-2.5">USD</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 text-slate-800">
                  {costs.map((row) => (
                    <tr key={row.model}>
                      <td className="px-3 py-2.5 font-mono text-xs font-bold">{row.model}</td>
                      <td className="px-3 py-2.5 font-mono text-xs">{row.calls}</td>
                      <td className="px-3 py-2.5 font-mono text-xs">{row.tokens_in}</td>
                      <td className="px-3 py-2.5 font-mono text-xs">{row.tokens_out}</td>
                      <td className="px-3 py-2.5 font-mono text-xs">{row.usd.toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : null}
        {!providers.data && !providers.isError && !providers.isLoading ? (
          <InfoMessage message="Cost totals will appear here once provider data loads." />
        ) : null}
      </section>
    </div>
  );
}
