"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { ZodError } from "zod";

import { ErrorMessage, InfoMessage } from "@/components/Message";
import { Metric } from "@/components/Metric";
import { PageHeader } from "@/components/PageHeader";
import { ProgressPanel } from "@/components/ProgressPanel";
import { api, UploadResponse } from "@/lib/api";
import { uploadFormSchema } from "@/lib/forms";

type Tab = "pdf" | "mapped" | "json";

export default function UploadPage() {
  const [tab, setTab] = useState<Tab>("pdf");
  const [result, setResult] = useState<UploadResponse | null>(null);

  return (
    <>
      <PageHeader
        title="Document Intake"
        description="Upload a loan-file packet, watch page results finish, then review the final checklist output."
      />
      <div className="mb-5 flex gap-2 border-b border-slate-200">
        <TabButton active={tab === "pdf"} onClick={() => setTab("pdf")}>
          PDF Upload
        </TabButton>
        <TabButton active={tab === "mapped"} onClick={() => setTab("mapped")}>
          Mapped Verification
        </TabButton>
        <TabButton active={tab === "json"} onClick={() => setTab("json")}>
          Partner JSON Intake
        </TabButton>
      </div>

      {tab === "pdf" ? <PdfUploadForm onUploaded={setResult} /> : null}
      {tab === "mapped" ? <MappedUploadForm onUploaded={setResult} /> : null}
      {tab === "json" ? <PartnerJsonForm onUploaded={setResult} /> : null}

      {result ? (
        <section className="mt-8 space-y-5 border-t border-slate-200 pt-6">
          <InfoMessage message={`Application ${result.application_id} accepted with status ${result.status}.`} />
          <div className="grid grid-cols-4 gap-3">
            <Metric label="Application" value={result.application_id} />
            <Metric label="Total pages" value={result.total_pages ?? "-"} />
            <Metric label="Digital" value={result.digital_pages ?? "-"} />
            <Metric label="Scanned" value={result.scanned_pages ?? "-"} />
          </div>
          <ProgressPanel applicationId={result.application_id} />
          <Link className="inline-block rounded bg-blue-700 px-4 py-2 text-sm font-medium text-white" href={`/applications/${result.application_id}`}>
            Open review
          </Link>
        </section>
      ) : null}
    </>
  );
}

function PdfUploadForm({ onUploaded }: { onUploaded: (result: UploadResponse) => void }) {
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setSubmitting] = useState(false);

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
        file: form.get("file"),
      });
      setSubmitting(true);
      onUploaded(await api.uploadPdf(payload));
      formElement.reset();
    } catch (err) {
      setError(formError(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="grid grid-cols-[1.15fr_0.85fr] gap-6" onSubmit={submit}>
      {error ? <div className="col-span-2"><ErrorMessage message={error} /></div> : null}
      <section className="space-y-4">
        <h2 className="text-lg font-semibold">Application Details</h2>
        <div className="grid grid-cols-2 gap-4">
          <TextField name="loanId" label="Loan ID" required />
          <SelectField name="productType" label="Product Type" options={["LAP", "MSME", "Personal Loan"]} />
        </div>
        <TextField name="applicantName" label="Applicant Name" required />
        <TextField name="coapplicantName" label="Co-applicant Name" />
        <TextField name="branch" label="Branch" required />
      </section>
      <section className="space-y-4">
        <h2 className="text-lg font-semibold">Document</h2>
        <input className="block w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm" name="file" type="file" accept="application/pdf" />
        <p className="text-sm text-slate-600">Select one PDF loan packet to begin.</p>
        <button disabled={isSubmitting} className="rounded bg-blue-700 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400">
          {isSubmitting ? "Submitting..." : "Submit for processing"}
        </button>
      </section>
    </form>
  );
}

function MappedUploadForm({ onUploaded }: { onUploaded: (result: UploadResponse) => void }) {
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const file = form.get("file");
    const rawManifest = String(form.get("manifest") ?? "");
    try {
      if (!(file instanceof File) || !file.name) {
        throw new Error("Mapped PDF or ZIP package is required");
      }
      const isZip = file.name.toLowerCase().endsWith(".zip");
      const manifest = rawManifest.trim() ? JSON.parse(rawManifest) : undefined;
      if (!isZip && !manifest) {
        throw new Error("Manifest JSON is required when uploading a PDF directly");
      }
      setSubmitting(true);
      onUploaded(await api.uploadMapped({ file, manifest }));
      formElement.reset();
    } catch (err) {
      setError(formError(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="space-y-4" onSubmit={submit}>
      {error ? <ErrorMessage message={error} /> : null}
      <h2 className="text-lg font-semibold">Trusted JSON + Page Mapping</h2>
      <input className="block w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm" name="file" type="file" accept="application/pdf,.pdf,application/zip,.zip" />
      <textarea
        className="h-80 w-full rounded border border-slate-300 px-3 py-2 font-mono text-sm"
        name="manifest"
        placeholder='Paste manifest JSON here, or upload a ZIP containing one PDF and one JSON manifest. If the ZIP has multiple PDFs, include "pdf_file": "loan-file.pdf" in the manifest.'
      />
      <button disabled={isSubmitting} className="rounded bg-blue-700 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400">
        {isSubmitting ? "Submitting..." : "Run Deterministic Verification"}
      </button>
    </form>
  );
}

function PartnerJsonForm({ onUploaded }: { onUploaded: (result: UploadResponse) => void }) {
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    try {
      const form = new FormData(event.currentTarget);
      const payload = JSON.parse(String(form.get("payload") ?? ""));
      setSubmitting(true);
      onUploaded(await api.uploadPartnerJson(payload));
    } catch (err) {
      setError(formError(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="space-y-4" onSubmit={submit}>
      {error ? <ErrorMessage message={error} /> : null}
      <h2 className="text-lg font-semibold">Partner OCR JSON Payload</h2>
      <textarea className="h-80 w-full rounded border border-slate-300 px-3 py-2 font-mono text-sm" name="payload" placeholder='{"loan_id":"LN-001","digital_text":{},"scanned_docs":{}}' />
      <button disabled={isSubmitting} className="rounded bg-blue-700 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400">
        {isSubmitting ? "Submitting..." : "Run Checklist Evaluation"}
      </button>
    </form>
  );
}

function TabButton({ active, children, onClick }: { active: boolean; children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`border-b-2 px-4 py-2 text-sm font-medium ${active ? "border-blue-700 text-blue-700" : "border-transparent text-slate-600"}`}
    >
      {children}
    </button>
  );
}

function TextField({ name, label, required = false }: { name: string; label: string; required?: boolean }) {
  return (
    <label className="block text-sm font-medium text-slate-700">
      {label}
      <input className="mt-1 block w-full rounded border border-slate-300 px-3 py-2" name={name} required={required} />
    </label>
  );
}

function SelectField({ name, label, options }: { name: string; label: string; options: string[] }) {
  return (
    <label className="block text-sm font-medium text-slate-700">
      {label}
      <select className="mt-1 block w-full rounded border border-slate-300 px-3 py-2" name={name}>
        {options.map((option) => (
          <option key={option}>{option}</option>
        ))}
      </select>
    </label>
  );
}

function formError(error: unknown): string {
  if (error instanceof ZodError) {
    return error.errors.map((item) => item.message).join("; ");
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Request failed";
}
