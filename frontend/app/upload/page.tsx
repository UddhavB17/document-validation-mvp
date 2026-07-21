"use client";

import Link from "next/link";
import { FormEvent, useState, useEffect } from "react";
import { ZodError } from "zod";

import { ErrorMessage, InfoMessage } from "@/components/Message";
import { Metric } from "@/components/Metric";
import { PageHeader } from "@/components/PageHeader";
import { ProgressPanel } from "@/components/ProgressPanel";
import { api, UploadResponse } from "@/lib/api";
import { uploadFormSchema } from "@/lib/forms";

type Tab = "pdf" | "mapped" | "json" | "zip";

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
        <TabButton active={tab === "zip"} onClick={() => setTab("zip")}>
          ZIP Package Intake
        </TabButton>
      </div>

      {tab === "pdf" ? <PdfUploadForm onUploaded={setResult} /> : null}
      {tab === "mapped" ? <MappedUploadForm onUploaded={setResult} /> : null}
      {tab === "json" ? <PartnerJsonForm onUploaded={setResult} /> : null}
      {tab === "zip" ? <ZipPackageForm onUploaded={setResult} /> : null}

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

function ZipPackageForm({ onUploaded }: { onUploaded: (result: UploadResponse) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [preparingPackageId, setPreparingPackageId] = useState<string | null>(null);
  const [progress, setProgress] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [isPreparing, setIsPreparing] = useState(false);
  const [isVerifying, setIsVerifying] = useState(false);
  const [manifestText, setManifestText] = useState("");

  useEffect(() => {
    if (!preparingPackageId) return;

    let active = true;
    const interval = setInterval(async () => {
      try {
        const res = await api.getZipPreparationProgress(preparingPackageId);
        if (!active) return;
        setProgress(res);
        if (res.status === "prepared" || res.status === "failed") {
          clearInterval(interval);
          setIsPreparing(false);
          if (res.status === "failed") {
            setError(res.error || "ZIP preparation failed");
            setPreparingPackageId(null);
          } else {
            const template = {
              schema_version: "1.0",
              loan_id: "LN-" + preparingPackageId.slice(0, 6).toUpperCase(),
              people: {
                primary: {
                  applicant_name: "Ramesh Kumar",
                  pan_number: "ABCDE1234F",
                  aadhaar_number: "123456789012"
                }
              },
              document_index: []
            };
            setManifestText(JSON.stringify(template, null, 2));
          }
        }
      } catch (err: any) {
        if (!active) return;
        clearInterval(interval);
        setIsPreparing(false);
        setError(err.message || "Failed to get preparation progress");
        setPreparingPackageId(null);
      }
    }, 2000);

    return () => {
      active = false;
      clearInterval(interval);
    };
  }, [preparingPackageId]);

  async function handlePrepare(event: FormEvent) {
    event.preventDefault();
    if (!file) {
      setError("Please select a ZIP file");
      return;
    }
    setError(null);
    setProgress(null);
    setIsPreparing(true);
    try {
      const res = await api.prepareZipPackage(file);
      setPreparingPackageId(res.package_id);
    } catch (err: any) {
      setError(err.message || "Failed to start ZIP preparation");
      setIsPreparing(false);
    }
  }

  async function handleVerify(event: FormEvent) {
    event.preventDefault();
    if (!preparingPackageId) return;
    setError(null);
    setIsVerifying(true);
    try {
      let manifest: any;
      try {
        manifest = JSON.parse(manifestText);
      } catch (err) {
        throw new Error("Invalid manifest JSON. Please ensure it is valid JSON.");
      }
      const res = await api.verifyZipPackage(preparingPackageId, manifest);
      onUploaded(res);
    } catch (err: any) {
      setError(err.message || "Verification failed");
    } finally {
      setIsVerifying(false);
    }
  }

  return (
    <div className="space-y-6">
      {error ? <ErrorMessage message={error} /> : null}

      {!progress || progress.status !== "prepared" ? (
        <form onSubmit={handlePrepare} className="space-y-4 max-w-xl">
          <h2 className="text-lg font-semibold">Step 1: Upload and Prepare ZIP</h2>
          <p className="text-sm text-slate-600">
            Upload the original ZIP package. Spreadsheets (.xlsx) are automatically rendered to readable PDF sheets, and images (.jpg/.png) are consolidated.
          </p>
          <input
            className="block w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm"
            type="file"
            accept=".zip,application/zip"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
          />
          <button
            type="submit"
            disabled={isPreparing || !file}
            className="rounded bg-blue-700 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400"
          >
            {isPreparing ? "Preparing ZIP..." : "Prepare ZIP and Build Page Inventory"}
          </button>

          {isPreparing && progress && (
            <div className="rounded bg-slate-50 border border-slate-200 p-4 space-y-2">
              <div className="text-sm font-medium text-slate-700">
                Stage: {progress.stage || "Initializing"}
              </div>
              <div className="text-sm text-slate-600">
                {progress.message || "Starting ZIP extraction..."}
              </div>
              {progress.total_files > 0 && (
                <div className="w-full bg-slate-200 rounded-full h-2">
                  <div
                    className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                    style={{
                      width: `${Math.round(((progress.processed_files || 0) / progress.total_files) * 100)}%`
                    }}
                  />
                </div>
              )}
            </div>
          )}
        </form>
      ) : (
        <form onSubmit={handleVerify} className="space-y-6">
          <div className="flex justify-between items-center">
            <h2 className="text-lg font-semibold text-slate-900">Step 2: Review Inventory & Mapped Verification</h2>
            <button
              type="button"
              onClick={() => {
                setProgress(null);
                setPreparingPackageId(null);
                setFile(null);
              }}
              className="text-sm text-blue-700 hover:underline"
            >
              Upload another ZIP
            </button>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <Metric label="Package" value={progress.package_id.slice(0, 8)} />
            <Metric label="Source files" value={progress.total_files} />
            <Metric label="Internal pages" value={progress.total_pages} />
          </div>

          <div className="space-y-2">
            <h3 className="text-sm font-semibold text-slate-700">Source Files Inventory</h3>
            <div className="overflow-x-auto rounded border border-slate-200 bg-white">
              <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
                <thead className="bg-slate-50 font-medium text-slate-600">
                  <tr>
                    <th className="px-4 py-2 border-b">ID</th>
                    <th className="px-4 py-2 border-b">Filename</th>
                    <th className="px-4 py-2 border-b">Type</th>
                    <th className="px-4 py-2 border-b">Worksheets</th>
                    <th className="px-4 py-2 border-b">Pages</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-slate-700">
                  {progress.documents?.map((doc: any) => (
                    <tr key={doc.source_document_id}>
                      <td className="px-4 py-2 font-mono text-xs">{doc.source_document_id}</td>
                      <td className="px-4 py-2 font-medium">{doc.original_filename}</td>
                      <td className="px-4 py-2 font-mono text-xs capitalize">{doc.file_type}</td>
                      <td className="px-4 py-2 text-slate-600">{doc.worksheets?.join(", ") || "-"}</td>
                      <td className="px-4 py-2 font-mono text-xs">
                        {doc.internal_page_start === doc.internal_page_end
                          ? doc.internal_page_start
                          : `${doc.internal_page_start}-${doc.internal_page_end}`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-slate-500">
              The internal page numbers will correspond to the consolidated PDF page layout for checking.
            </p>
          </div>

          <div className="space-y-2">
            <label className="block text-sm font-medium text-slate-700">
              Trusted JSON or Raw Company Database Dump for this ZIP
              <span className="block font-normal text-xs text-slate-500 mt-1">
                Supply the JSON manifest or paste the raw text output from the database application.
              </span>
            </label>
            <textarea
              value={manifestText}
              onChange={(e) => setManifestText(e.target.value)}
              className="h-80 w-full rounded border border-slate-300 px-3 py-2 font-mono text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              placeholder="Paste manifest or database dump here..."
            />
          </div>

          <button
            type="submit"
            disabled={isVerifying}
            className="rounded bg-blue-700 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-400"
          >
            {isVerifying ? "Verifying..." : "Identify and Verify ZIP Documents"}
          </button>
        </form>
      )}
    </div>
  );
}
