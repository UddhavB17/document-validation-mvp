"use client";

import { FormEvent, useRef, useState } from "react";

import { ErrorMessage } from "@/components/Message";
import { api, UploadResponse } from "@/lib/api";
import { uploadFormSchema } from "@/lib/forms";

import { BatchStatusTable } from "./BatchStatusTable";
import { PdfFilePreview } from "./PdfFilePreview";
import { SelectField, TextField } from "./UploadField";
import { CASE_TYPE_OPTIONS, getFormError } from "./uploadUtils";
import { UploadFormProps } from "./types";

export function PdfUploadForm({ onUploaded }: UploadFormProps) {
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setSubmitting] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [batchId, setBatchId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    try {
      if (selectedFiles.length > 1) {
        setSubmitting(true);
        const batch = await api.uploadBatch(selectedFiles);
        setBatchId(batch.batch_id);
        formElement.reset();
        setSelectedFiles([]);
        return;
      }
      const payload = uploadFormSchema.parse({
        loanId: form.get("loanId"),
        applicantName: form.get("applicantName"),
        coapplicantName: form.get("coapplicantName") || undefined,
        productType: form.get("productType"),
        branch: form.get("branch"),
        caseType: form.get("caseType"),
        applicationDate: form.get("applicationDate"),
        file: form.get("file"),
      });
      setSubmitting(true);
      const result: UploadResponse = await api.uploadPdf(payload);
      onUploaded(result);
      formElement.reset();
      setSelectedFiles([]);
      setBatchId(null);
    } catch (submissionError) {
      setError(getFormError(submissionError));
    } finally {
      setSubmitting(false);
    }
  }

  function removeSelectedFile(name: string) {
    setSelectedFiles((current) => current.filter((file) => file.name !== name));
    if (fileInputRef.current && selectedFiles.length <= 1) fileInputRef.current.value = "";
  }

  return (
    <div className="space-y-6">
      <form className="grid grid-cols-1 md:grid-cols-2 gap-8" onSubmit={submit}>
        {error ? <div className="col-span-2"><ErrorMessage message={error} /></div> : null}
        <section className="space-y-4">
          <h2 className="font-serif text-[16px] font-bold text-[#16202E] border-b border-slate-100 pb-2 mb-4">Application Details</h2>
          <div className="grid grid-cols-2 gap-4">
            <TextField name="loanId" label="Loan ID" required />
            <SelectField name="productType" label="Product Type" options={["LAP", "MSME", "Personal Loan"]} />
          </div>
          <SelectField name="caseType" label="Case Type" options={CASE_TYPE_OPTIONS} />
          <TextField name="applicantName" label="Applicant Name" required />
          <TextField name="coapplicantName" label="Co-applicant Name" />
          <TextField name="branch" label="Branch" required />
          <TextField name="applicationDate" label="Application Date" type="date" required />
        </section>
        <section className="space-y-4 flex flex-col justify-between">
          <div className="space-y-4">
            <h2 className="font-serif text-[16px] font-bold text-[#16202E] border-b border-slate-100 pb-2 mb-4">Document Files</h2>
            <label className="block">
              <span className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">Loan Packet PDFs (up to 10)</span>
              <input
                ref={fileInputRef}
                className="block w-full text-sm text-slate-500 file:mr-4 file:py-2.5 file:px-4 file:rounded-lg file:border border-[#E1E5EB] bg-white file:text-xs file:font-semibold file:bg-[#F6F7FA] file:text-slate-700 hover:file:bg-slate-100 file:cursor-pointer rounded-lg px-4 py-2.5 focus:outline-none"
                name="file"
                type="file"
                accept="application/pdf,.pdf"
                multiple
                required
                onChange={(fileEvent) => {
                  const picked = Array.from(fileEvent.target.files ?? []).slice(0, 10);
                  setSelectedFiles(picked);
                  setBatchId(null);
                }}
              />
            </label>
            <p className="text-xs text-[#5C6B7A] font-medium leading-relaxed">Select up to ten PDF files. Each file is processed separately and listed below.</p>
            {selectedFiles.map((file) => (
              <PdfFilePreview key={file.name} file={file} onRemove={() => removeSelectedFile(file.name)} />
            ))}
          </div>
          <button
            type="submit"
            disabled={isSubmitting || selectedFiles.length === 0}
            className="w-full md:w-auto px-5 py-3 text-sm font-semibold rounded-lg bg-[#2B4C7E] hover:bg-[#1E3559] text-white transition-all duration-150 shadow-3xs disabled:bg-slate-200 disabled:text-slate-500 border-none cursor-pointer"
          >
            {isSubmitting ? "Submitting..." : selectedFiles.length > 1 ? `Submit ${selectedFiles.length} files for processing` : "Submit for processing"}
          </button>
        </section>
      </form>
      {batchId ? <BatchStatusTable batchId={batchId} /> : null}
    </div>
  );
}
