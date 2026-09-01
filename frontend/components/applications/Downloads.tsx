import { api } from "@/lib/api";

export function Downloads({ applicationId }: { applicationId: number }) {
  return (
    <section className="space-y-3">
      <h2 className="text-base font-bold text-slate-800">Downloads</h2>
      <a className="inline-block rounded-lg border border-slate-300 bg-white hover:bg-slate-50 px-5 py-2 text-sm font-semibold text-slate-700 shadow-sm transition-colors" href={api.ocrJsonUrl(applicationId)} download>
        Download Document OCR JSON
      </a>
    </section>
  );
}
