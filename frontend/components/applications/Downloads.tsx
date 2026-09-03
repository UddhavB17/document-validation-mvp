import { api } from "@/lib/api";

export function Downloads({ applicationId }: { applicationId: number }) {
  return (
    <section className="min-w-0 space-y-5">
      <div>
        <h2 className="text-base font-bold text-slate-800">Files</h2>
        <p className="mt-1 text-xs font-medium text-[#5C6B7A]">Open the original source file or download the bounded OCR export for this case.</p>
      </div>

      <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs font-semibold leading-relaxed text-amber-900">
        These files may contain sensitive borrower data, including PAN, Aadhaar, bank account numbers, addresses, and contact details. Handle them according to your organization&apos;s access and retention policy.
      </div>

      <div className="grid min-w-0 gap-3 sm:grid-cols-2">
        <a
          className="flex min-w-0 items-center justify-between rounded-xl border border-[#E1E5EB] bg-white px-4 py-3 text-sm font-bold text-[#2B4C7E] shadow-3xs transition-colors hover:bg-[#EAF0F8]"
          href={api.sourcePdfUrl(applicationId)}
          target="_blank"
          rel="noreferrer"
        >
          <span>Open source PDF</span>
          <span aria-hidden="true">↗</span>
        </a>
        <a
          className="flex min-w-0 items-center justify-between rounded-xl border border-[#E1E5EB] bg-white px-4 py-3 text-sm font-bold text-[#2B4C7E] shadow-3xs transition-colors hover:bg-[#EAF0F8]"
          href={api.ocrJsonUrl(applicationId)}
          download
        >
          <span>Download OCR JSON</span>
          <span aria-hidden="true">↓</span>
        </a>
      </div>
    </section>
  );
}
