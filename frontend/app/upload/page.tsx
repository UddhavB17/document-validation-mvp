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
import { StatusBadge } from "@/components/StatusBadge";

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
      <div className="mb-6 flex gap-2 border-b border-slate-200">
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

      <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm">
        {tab === "pdf" ? <PdfUploadForm onUploaded={setResult} /> : null}
        {tab === "mapped" ? <MappedUploadForm onUploaded={setResult} /> : null}
        {tab === "json" ? <PartnerJsonForm onUploaded={setResult} /> : null}
        {tab === "zip" ? <ZipPackageForm onUploaded={setResult} /> : null}
      </div>

      {result ? (
        <section className="mt-8 space-y-6 border-t border-slate-200 pt-6">
          <InfoMessage message={`Application ${result.application_id} accepted with status ${result.status}.`} />
          <div className="grid grid-cols-4 gap-4">
            <Metric label="Application ID" value={result.application_id} />
            <Metric label="Total Pages" value={result.total_pages ?? "-"} />
            <Metric label="Digital Count" value={result.digital_pages ?? "-"} />
            <Metric label="Scanned Count" value={result.scanned_pages ?? "-"} />
          </div>
          <ProgressPanel applicationId={result.application_id} />
          <Link className="inline-block rounded-lg bg-blue-50 border border-blue-200 px-5 py-2.5 text-sm font-bold text-blue-700 shadow-sm hover:bg-blue-100 transition-colors duration-150" href={`/applications/${result.application_id}`}>
            Open Completed Review
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
    <form className="grid grid-cols-1 md:grid-cols-2 gap-6" onSubmit={submit}>
      {error ? <div className="col-span-2"><ErrorMessage message={error} /></div> : null}
      <section className="space-y-4">
        <h2 className="text-lg font-bold text-slate-800">Application Details</h2>
        <div className="grid grid-cols-2 gap-4">
          <TextField name="loanId" label="Loan ID" required />
          <SelectField name="productType" label="Product Type" options={["LAP", "MSME", "Personal Loan"]} />
        </div>
        <TextField name="applicantName" label="Applicant Name" required />
        <TextField name="coapplicantName" label="Co-applicant Name" />
        <TextField name="branch" label="Branch" required />
      </section>
      <section className="space-y-4 flex flex-col justify-between">
        <div className="space-y-4">
          <h2 className="text-lg font-bold text-slate-800">Document File</h2>
          <label className="block">
            <span className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Loan Packet PDF</span>
            <input className="block w-full text-sm text-slate-500 file:mr-4 file:py-2.5 file:px-4 file:rounded-lg file:border border-slate-300 bg-white file:text-xs file:font-semibold file:bg-slate-100 file:text-slate-700 hover:file:bg-slate-200 file:cursor-pointer rounded-lg px-4 py-2.5 focus:outline-none" name="file" type="file" accept="application/pdf" />
          </label>
          <p className="text-xs text-slate-500 font-medium">Select a single PDF file containing all applicant KYC and loan documentation.</p>
        </div>
        <button disabled={isSubmitting} className="w-full md:w-auto px-5 py-3 text-sm font-semibold rounded-lg bg-blue-700 hover:bg-blue-600 text-white transition-all duration-150 shadow-sm disabled:bg-slate-300 disabled:text-slate-500">
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
    <form className="space-y-5" onSubmit={submit}>
      {error ? <ErrorMessage message={error} /> : null}
      <div className="space-y-2">
        <h2 className="text-lg font-bold text-slate-800">Trusted JSON + Page Mapping</h2>
        <p className="text-xs text-slate-500 font-medium">Verify pages in a PDF using deterministic templates and database hashes.</p>
      </div>
      <label className="block">
        <span className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Select file (PDF or ZIP package)</span>
        <input className="block w-full text-sm text-slate-500 file:mr-4 file:py-2.5 file:px-4 file:rounded-lg file:border border-slate-300 bg-white file:text-xs file:font-semibold file:bg-slate-100 file:text-slate-700 hover:file:bg-slate-200 file:cursor-pointer rounded-lg px-4 py-2.5 focus:outline-none" name="file" type="file" accept="application/pdf,.pdf,application/zip,.zip" />
      </label>
      <label className="block">
        <span className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Manifest JSON</span>
        <textarea
          className="h-64 w-full rounded-lg border border-slate-300 bg-white px-4 py-3 font-mono text-sm text-slate-900 placeholder-slate-400 focus:border-blue-600 focus:outline-none focus:ring-1 focus:ring-blue-600 shadow-sm"
          name="manifest"
          placeholder='Paste manifest JSON here, or upload a ZIP containing one PDF and one JSON manifest. If the ZIP has multiple PDFs, include "pdf_file": "loan-file.pdf" in the manifest.'
        />
      </label>
      <button disabled={isSubmitting} className="px-5 py-2.5 text-sm font-semibold rounded-lg bg-blue-700 hover:bg-blue-600 text-white transition-all duration-150 shadow-sm disabled:bg-slate-300 disabled:text-slate-500">
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
    <form className="space-y-5" onSubmit={submit}>
      {error ? <ErrorMessage message={error} /> : null}
      <div className="space-y-2">
        <h2 className="text-lg font-bold text-slate-800">Partner OCR JSON Payload</h2>
        <p className="text-xs text-slate-500 font-medium">Evaluate the checklist engine directly using a pre-extracted partner OCR JSON payload.</p>
      </div>
      <label className="block">
        <span className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">OCR JSON Payload</span>
        <textarea className="h-64 w-full rounded-lg border border-slate-300 bg-white px-4 py-3 font-mono text-sm text-slate-900 placeholder-slate-400 focus:border-blue-600 focus:outline-none focus:ring-1 focus:ring-blue-600 shadow-sm" name="payload" placeholder='{"loan_id":"LN-001","digital_text":{},"scanned_docs":{}}' />
      </label>
      <button disabled={isSubmitting} className="px-5 py-2.5 text-sm font-semibold rounded-lg bg-blue-700 hover:bg-blue-600 text-white transition-all duration-150 shadow-sm disabled:bg-slate-300 disabled:text-slate-500">
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
      className={`border-b-2 px-5 py-3 text-sm font-semibold transition-all duration-150 select-none ${
        active 
          ? "border-blue-700 text-blue-700 font-bold" 
          : "border-transparent text-slate-500 hover:text-slate-800"
      }`}
    >
      {children}
    </button>
  );
}

function TextField({ name, label, required = false }: { name: string; label: string; required?: boolean }) {
  return (
    <label className="block text-sm font-medium">
      <span className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">{label}</span>
      <input className="block w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-slate-950 focus:border-blue-600 focus:outline-none focus:ring-1 focus:ring-blue-600 shadow-sm" name={name} required={required} />
    </label>
  );
}

function SelectField({ name, label, options }: { name: string; label: string; options: string[] }) {
  return (
    <label className="block text-sm font-medium">
      <span className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">{label}</span>
      <select className="block w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-slate-950 focus:border-blue-600 focus:outline-none focus:ring-1 focus:ring-blue-600 shadow-sm cursor-pointer" name={name}>
        {options.map((option) => (
          <option key={option} className="bg-white text-slate-900">{option}</option>
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
        <form onSubmit={handlePrepare} className="space-y-5 max-w-xl">
          <div className="space-y-2">
            <h2 className="text-lg font-bold text-slate-800">Step 1: Upload and Prepare ZIP Folder</h2>
            <p className="text-xs text-slate-550 font-medium leading-relaxed">
              Upload the original ZIP package. Spreadsheets (.xlsx) are automatically rendered to readable PDF sheets, and images (.jpg/.png) are consolidated.
            </p>
          </div>
          <label className="block">
            <span className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Intake ZIP Archive</span>
            <input
              className="block w-full text-sm text-slate-500 file:mr-4 file:py-2.5 file:px-4 file:rounded-lg file:border border-slate-300 bg-white file:text-xs file:font-semibold file:bg-slate-100 file:text-slate-700 hover:file:bg-slate-200 file:cursor-pointer rounded-lg px-4 py-2.5 focus:outline-none"
              type="file"
              accept=".zip,application/zip"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
          </label>
          <button
            type="submit"
            disabled={isPreparing || !file}
            className="px-5 py-2.5 text-sm font-semibold rounded-lg bg-blue-700 hover:bg-blue-600 text-white transition-all duration-150 shadow-sm disabled:bg-slate-300 disabled:text-slate-500"
          >
            {isPreparing ? "Preparing ZIP Archive..." : "Extract ZIP and Build Page Inventory"}
          </button>

          {isPreparing && progress && (
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-5 space-y-3 shadow-inner">
              <div className="flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
                <span>Stage: {progress.stage || "Initializing"}</span>
                <span className="text-blue-700 font-mono">
                  {progress.processed_files || 0} / {progress.total_files || 0} files
                </span>
              </div>
              <div className="text-sm font-semibold text-slate-800">
                {progress.message || "Starting ZIP extraction..."}
              </div>
              {progress.total_files > 0 && (
                <div className="w-full bg-slate-200 border border-slate-300 rounded-full h-2.5 overflow-hidden shadow-inner">
                  <div
                    className="bg-blue-600 h-full rounded-full transition-all duration-300"
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
          <div className="flex justify-between items-center border-b border-slate-200 pb-3">
            <h2 className="text-lg font-bold text-slate-800">Step 2: Review Inventory & Mapped Verification</h2>
            <button
              type="button"
              onClick={() => {
                setProgress(null);
                setPreparingPackageId(null);
                setFile(null);
              }}
              className="text-xs font-bold text-blue-700 hover:underline flex items-center gap-1"
            >
              🔄 Upload another ZIP
            </button>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <Metric label="Package ID" value={progress.package_id.slice(0, 8)} />
            <Metric label="Source files" value={progress.total_files} />
            <Metric label="Internal pages" value={progress.total_pages} />
          </div>

          <div className="space-y-3">
            <h3 className="text-sm font-bold text-slate-700">Source Files Inventory</h3>
            <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
              <table className="min-w-full divide-y divide-slate-200 text-left text-xs">
                <thead className="bg-slate-50 font-bold uppercase tracking-wider text-slate-500">
                  <tr>
                    <th className="px-4 py-3 border-b border-slate-200">ID</th>
                    <th className="px-4 py-3 border-b border-slate-200">Filename</th>
                    <th className="px-4 py-3 border-b border-slate-200">Type</th>
                    <th className="px-4 py-3 border-b border-slate-200">Worksheets</th>
                    <th className="px-4 py-3 border-b border-slate-200">Page Ranges</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-slate-700">
                  {progress.documents?.map((doc: any) => (
                    <tr key={doc.source_document_id} className="hover:bg-slate-50/50 transition-colors duration-100">
                      <td className="px-4 py-3 font-mono text-blue-700 font-semibold">{doc.source_document_id}</td>
                      <td className="px-4 py-3 font-semibold">{doc.original_filename}</td>
                      <td className="px-4 py-3"><StatusBadge status={doc.file_type} /></td>
                      <td className="px-4 py-3 text-slate-500 font-medium">{doc.worksheets?.join(", ") || "-"}</td>
                      <td className="px-4 py-3 font-mono font-semibold text-slate-800">
                        {doc.internal_page_start === doc.internal_page_end
                          ? doc.internal_page_start
                          : `${doc.internal_page_start} - ${doc.internal_page_end}`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-[11px] text-slate-500 font-medium">
              * Note: The internal page numbers correspond to the consolidated PDF page layout for verification matches.
            </p>
          </div>

          <div className="space-y-2">
            <label className="block text-sm font-bold text-slate-700">
              Trusted JSON or Raw Company Database Dump for this ZIP
              <span className="block font-normal text-xs text-slate-500 mt-1">
                Supply the JSON manifest or paste the raw text output from the database application.
              </span>
            </label>
            <textarea
              value={manifestText}
              onChange={(e) => setManifestText(e.target.value)}
              className="h-80 w-full rounded-lg border border-slate-300 bg-white px-4 py-3 font-mono text-sm text-slate-900 placeholder-slate-400 focus:border-blue-650 focus:outline-none focus:ring-1 focus:ring-blue-650 shadow-sm"
              placeholder="Paste manifest or database dump here..."
            />
          </div>

          <button
            type="submit"
            disabled={isVerifying}
            className="px-5 py-2.5 text-sm font-semibold rounded-lg bg-blue-700 hover:bg-blue-600 text-white transition-all duration-150 shadow-sm disabled:bg-slate-300 disabled:text-slate-500"
          >
            {isVerifying ? "Verifying..." : "Identify and Verify ZIP Documents"}
          </button>
        </form>
      )}
    </div>
  );
}
