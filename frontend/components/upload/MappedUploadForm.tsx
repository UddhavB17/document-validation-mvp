"use client";

import { FormEvent, useRef, useState } from "react";

import { ErrorMessage } from "@/components/Message";
import { PdfFilePreview } from "@/components/upload/PdfFilePreview";
import { SelectField } from "@/components/upload/FormFields";
import { api, UploadResponse } from "@/lib/api";
import { CaseType } from "@/lib/types";
import { formError, getSanitizedManifest, isPdfFile } from "@/lib/uploadUtils";

export function MappedUploadForm({ onUploaded }: { onUploaded: (result: UploadResponse) => void }) {
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setSubmitting] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const file = form.get("file");
    const rawManifest = String(form.get("manifest") ?? "");
    const caseType = String(form.get("caseType") ?? "Normal Case") as CaseType;
    try {
      if (!(file instanceof File) || !file.name) {
        throw new Error("Mapped PDF or ZIP package is required");
      }
      const isZip = file.name.toLowerCase().endsWith(".zip");
      const manifest = rawManifest.trim() ? getSanitizedManifest(rawManifest) : undefined;
      if (!isZip && !manifest) {
        throw new Error("Manifest JSON or database dump is required when uploading a PDF directly");
      }
      setSubmitting(true);
      onUploaded(await api.uploadMapped({ file, manifest, caseType }));
      formElement.reset();
      setSelectedFile(null);
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
        <h2 className="font-serif text-[16px] font-bold text-[#16202E] border-b border-slate-100 pb-2 mb-2">Trusted JSON + Page Mapping</h2>
        <p className="text-xs text-[#5C6B7A] font-medium leading-relaxed">
          Verify pages in a PDF using deterministic templates and database hashes.
        </p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <SelectField name="caseType" label="Case Type" options={["Normal Case", "BT Case"]} />
        <label className="block">
          <span className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">Select file (PDF or ZIP package)</span>
          <input
            ref={fileInputRef}
            className="block w-full text-sm text-slate-500 file:mr-4 file:py-2.5 file:px-4 file:rounded-lg file:border border-[#E1E5EB] bg-white file:text-xs file:font-semibold file:bg-[#F6F7FA] file:text-slate-700 hover:file:bg-slate-100 file:cursor-pointer rounded-lg px-4 py-2.5 focus:outline-none"
            name="file"
            type="file"
            accept="application/pdf,.pdf,application/zip,.zip"
            required
            onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
          />
        </label>
      </div>
      {selectedFile && isPdfFile(selectedFile) ? (
        <PdfFilePreview
          file={selectedFile}
          onRemove={() => {
            setSelectedFile(null);
            if (fileInputRef.current) fileInputRef.current.value = "";
          }}
        />
      ) : null}
      <label className="block">
        <span className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">Manifest JSON</span>
        <textarea
          className="h-48 w-full rounded-lg border border-[#E1E5EB] bg-white px-4 py-3 font-mono text-sm text-[#16202E] placeholder-slate-400 focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs"
          name="manifest"
          placeholder='Paste manifest JSON here, or upload a ZIP containing one PDF and one JSON manifest. If the ZIP has multiple PDFs, include "pdf_file": "loan-file.pdf" in the manifest.'
        />
      </label>
      <button
        disabled={isSubmitting || !selectedFile}
        className="px-5 py-2.5 text-sm font-semibold rounded-lg bg-[#2B4C7E] hover:bg-[#1E3559] text-white transition-all duration-150 shadow-3xs disabled:bg-slate-200 disabled:text-slate-500 border-none cursor-pointer"
      >
        {isSubmitting ? "Submitting..." : "Run Deterministic Verification"}
      </button>
    </form>
  );
}
