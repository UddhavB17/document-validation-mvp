"use client";

import { FormEvent, useState } from "react";

import { ErrorMessage } from "@/components/Message";
import { api, UploadResponse } from "@/lib/api";
import { escapeControlCharacters, formError } from "@/lib/uploadUtils";

export function PartnerJsonForm({ onUploaded }: { onUploaded: (result: UploadResponse) => void }) {
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    try {
      const form = new FormData(event.currentTarget);
      const payload = JSON.parse(escapeControlCharacters(String(form.get("payload") ?? "")));
      setSubmitting(true);
      onUploaded(await api.uploadPartnerJson(payload));
    } catch (err) {
      setError(formError(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="space-y-5" onSubmit={submit}>
      {error ? <ErrorMessage message={error} /> : null}
      <div className="space-y-2">
        <h2 className="font-serif text-[16px] font-bold text-[#16202E] border-b border-slate-100 pb-2 mb-2">Partner OCR JSON Payload</h2>
        <p className="text-xs text-[#5C6B7A] font-medium leading-relaxed">
          Evaluate the checklist engine directly using a pre-extracted partner OCR JSON payload.
        </p>
      </div>
      <label className="block">
        <span className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">OCR JSON Payload</span>
        <textarea
          className="h-64 w-full rounded-lg border border-[#E1E5EB] bg-white px-4 py-3 font-mono text-sm text-[#16202E] placeholder-slate-400 focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs"
          name="payload"
          placeholder='{"loan_id":"LN-001","digital_text":{},"scanned_docs":{}}'
        />
      </label>
      <button
        disabled={isSubmitting}
        className="px-5 py-2.5 text-sm font-semibold rounded-lg bg-[#2B4C7E] hover:bg-[#1E3559] text-white transition-all duration-150 shadow-3xs disabled:bg-slate-200 disabled:text-slate-500 border-none cursor-pointer"
      >
        {isSubmitting ? "Submitting..." : "Run Checklist Evaluation"}
      </button>
    </form>
  );
}
