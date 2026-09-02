"use client";

import { FormEvent, useRef, useState } from "react";

import { ErrorMessage } from "@/components/Message";
import { PdfFilePreview } from "@/components/upload/PdfFilePreview";
import { SelectField, TextField } from "@/components/upload/FormFields";
import { api, UploadResponse } from "@/lib/api";
import { uploadFormSchema } from "@/lib/forms";
import { formError } from "@/lib/uploadUtils";

export function PdfUploadForm({ onUploaded }: { onUploaded: (result: UploadResponse) => void }) {
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setSubmitting] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    try {
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
      onUploaded(await api.uploadPdf(payload));
      formElement.reset();
      setSelectedFile(null);
    } catch (err) {
      setError(formError(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="grid grid-cols-1 md:grid-cols-2 gap-8" onSubmit={submit}>
      {error ? (
        <div className="col-span-2">
          <ErrorMessage message={error} />
        </div>
      ) : null}
      <section className="space-y-4">
        <h2 className="font-serif text-[16px] font-bold text-[#16202E] border-b border-slate-100 pb-2 mb-4">Application Details</h2>
        <div className="grid grid-cols-2 gap-4">
          <TextField name="loanId" label="Loan ID" required />
          <SelectField name="productType" label="Product Type" options={["LAP", "MSME", "Personal Loan"]} />
        </div>
        <SelectField name="caseType" label="Case Type" options={["Normal Case", "BT Case"]} />
        <TextField name="applicantName" label="Applicant Name" required />
        <TextField name="coapplicantName" label="Co-applicant Name" />
        <TextField name="branch" label="Branch" required />
        <TextField name="applicationDate" label="Application Date" type="date" required />
      </section>
      <section className="space-y-4 flex flex-col justify-between">
        <div className="space-y-4">
          <h2 className="font-serif text-[16px] font-bold text-[#16202E] border-b border-slate-100 pb-2 mb-4">Document File</h2>
          <label className="block">
            <span className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">Loan Packet PDF</span>
            <input
              ref={fileInputRef}
              className="block w-full text-sm text-slate-500 file:mr-4 file:py-2.5 file:px-4 file:rounded-lg file:border border-[#E1E5EB] bg-white file:text-xs file:font-semibold file:bg-[#F6F7FA] file:text-slate-700 hover:file:bg-slate-100 file:cursor-pointer rounded-lg px-4 py-2.5 focus:outline-none"
              name="file"
              type="file"
              accept="application/pdf,.pdf"
              required
              onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
            />
          </label>
          <p className="text-xs text-[#5C6B7A] font-medium leading-relaxed">
            Select a single PDF file containing all applicant KYC and loan documentation.
          </p>
          {selectedFile ? (
            <PdfFilePreview
              file={selectedFile}
              onRemove={() => {
                setSelectedFile(null);
                if (fileInputRef.current) fileInputRef.current.value = "";
              }}
            />
          ) : null}
        </div>
        <button
          disabled={isSubmitting || !selectedFile}
          className="w-full md:w-auto px-5 py-3 text-sm font-semibold rounded-lg bg-[#2B4C7E] hover:bg-[#1E3559] text-white transition-all duration-150 shadow-3xs disabled:bg-slate-200 disabled:text-slate-500 border-none cursor-pointer"
        >
          {isSubmitting ? "Submitting..." : "Submit for processing"}
        </button>
      </section>
    </form>
  );
}
