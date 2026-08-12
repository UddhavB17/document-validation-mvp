"use client";

import Link from "next/link";
import { FormEvent, useState, useEffect, useRef } from "react";
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
    <form className="grid grid-cols-1 md:grid-cols-2 gap-6" onSubmit={submit}>
      {error ? <div className="col-span-2"><ErrorMessage message={error} /></div> : null}
      <section className="space-y-4">
        <h2 className="text-lg font-bold text-slate-800">Application Details</h2>
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
          <h2 className="text-lg font-bold text-slate-800">Document File</h2>
          <label className="block">
            <span className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Loan Packet PDF</span>
            <input
              ref={fileInputRef}
              className="block w-full text-sm text-slate-500 file:mr-4 file:py-2.5 file:px-4 file:rounded-lg file:border border-slate-300 bg-white file:text-xs file:font-semibold file:bg-slate-100 file:text-slate-700 hover:file:bg-slate-200 file:cursor-pointer rounded-lg px-4 py-2.5 focus:outline-none"
              name="file"
              type="file"
              accept="application/pdf,.pdf"
              required
              onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
            />
          </label>
          <p className="text-xs text-slate-500 font-medium">Select a single PDF file containing all applicant KYC and loan documentation.</p>
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
        <button disabled={isSubmitting || !selectedFile} className="w-full md:w-auto px-5 py-3 text-sm font-semibold rounded-lg bg-blue-700 hover:bg-blue-600 text-white transition-all duration-150 shadow-sm disabled:bg-slate-300 disabled:text-slate-500">
          {isSubmitting ? "Submitting..." : "Submit for processing"}
        </button>
      </section>
    </form>
  );
}

function MappedUploadForm({ onUploaded }: { onUploaded: (result: UploadResponse) => void }) {
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
    const caseType = String(form.get("caseType") ?? "Normal Case") as "Normal Case" | "BT Case";
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
        <h2 className="text-lg font-bold text-slate-800">Trusted JSON + Page Mapping</h2>
        <p className="text-xs text-slate-500 font-medium">Verify pages in a PDF using deterministic templates and database hashes.</p>
      </div>
      <SelectField name="caseType" label="Case Type" options={["Normal Case", "BT Case"]} />
      <label className="block">
        <span className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Select file (PDF or ZIP package)</span>
        <input
          ref={fileInputRef}
          className="block w-full text-sm text-slate-500 file:mr-4 file:py-2.5 file:px-4 file:rounded-lg file:border border-slate-300 bg-white file:text-xs file:font-semibold file:bg-slate-100 file:text-slate-700 hover:file:bg-slate-200 file:cursor-pointer rounded-lg px-4 py-2.5 focus:outline-none"
          name="file"
          type="file"
          accept="application/pdf,.pdf,application/zip,.zip"
          required
          onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
        />
      </label>
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
        <span className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Manifest JSON</span>
        <textarea
          className="h-64 w-full rounded-lg border border-slate-300 bg-white px-4 py-3 font-mono text-sm text-slate-900 placeholder-slate-400 focus:border-blue-600 focus:outline-none focus:ring-1 focus:ring-blue-600 shadow-sm"
          name="manifest"
          placeholder='Paste manifest JSON here, or upload a ZIP containing one PDF and one JSON manifest. If the ZIP has multiple PDFs, include "pdf_file": "loan-file.pdf" in the manifest.'
        />
      </label>
      <button disabled={isSubmitting || !selectedFile} className="px-5 py-2.5 text-sm font-semibold rounded-lg bg-blue-700 hover:bg-blue-600 text-white transition-all duration-150 shadow-sm disabled:bg-slate-300 disabled:text-slate-500">
        {isSubmitting ? "Submitting..." : "Run Deterministic Verification"}
      </button>
    </form>
  );
}

function PdfFilePreview({ file, onRemove }: { file: File; onRemove: () => void }) {
  const [objectUrl, setObjectUrl] = useState("");
  const [previewError, setPreviewError] = useState<string | null>(null);

  useEffect(() => {
    const nextUrl = URL.createObjectURL(file);
    setObjectUrl(nextUrl);
    return () => URL.revokeObjectURL(nextUrl);
  }, [file]);

  function openPreview() {
    if (!objectUrl) return;
    const previewWindow = window.open(objectUrl, "_blank");
    if (!previewWindow) {
      setPreviewError("The browser blocked the preview tab. Allow pop-ups for this local app and try again.");
      return;
    }
    previewWindow.opener = null;
    setPreviewError(null);
  }

  return (
    <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 shadow-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="text-xs font-bold uppercase tracking-wider text-blue-700">Selected PDF</div>
          <div className="truncate text-sm font-bold text-slate-900" title={file.name}>{file.name}</div>
          <div className="text-xs font-medium text-slate-500">{formatFileSize(file.size)} · Opens locally in a new tab for confirmation</div>
        </div>
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            onClick={openPreview}
            disabled={!objectUrl}
            className="rounded-lg bg-blue-700 px-4 py-2 text-xs font-bold text-white shadow-sm hover:bg-blue-600 disabled:bg-slate-300"
          >
            Open PDF Preview
          </button>
          <button
            type="button"
            onClick={onRemove}
            className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-xs font-bold text-slate-700 hover:bg-slate-50"
          >
            Remove
          </button>
        </div>
      </div>
      {previewError ? <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-800">{previewError}</div> : null}
    </div>
  );
}

function isPdfFile(file: File): boolean {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function PartnerJsonForm({ onUploaded }: { onUploaded: (result: UploadResponse) => void }) {
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

function TextField({
  name,
  label,
  required = false,
  type = "text",
}: {
  name: string;
  label: string;
  required?: boolean;
  type?: string;
}) {
  return (
    <label className="block text-sm font-medium">
      <span className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">{label}</span>
      <input className="block w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-slate-950 focus:border-blue-600 focus:outline-none focus:ring-1 focus:ring-blue-600 shadow-sm" name={name} type={type} required={required} />
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
  const [caseType, setCaseType] = useState<"Normal Case" | "BT Case">("Normal Case");

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
      const manifest = getSanitizedManifest(manifestText);
      const res = await api.verifyZipPackage(preparingPackageId, manifest, caseType);
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
              Upload another ZIP
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
                    <th className="px-4 py-3 border-b border-slate-200">Inferred Document</th>
                    <th className="px-4 py-3 border-b border-slate-200">Format</th>
                    <th className="px-4 py-3 border-b border-slate-200">Worksheets</th>
                    <th className="px-4 py-3 border-b border-slate-200">Page Ranges</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-slate-700">
                  {progress.documents?.map((doc: any) => (
                    <tr key={doc.source_document_id} className="hover:bg-slate-50/50 transition-colors duration-100">
                      <td className="px-4 py-3 font-mono text-blue-700 font-semibold">{doc.source_document_id}</td>
                      <td className="px-4 py-3 font-semibold">{doc.original_filename}</td>
                      <td className="px-4 py-3 font-semibold text-slate-800">
                        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-blue-50 text-blue-700 border border-blue-100">
                          {inferDocumentType(doc.original_filename)}
                        </span>
                      </td>
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

          <label className="block max-w-sm text-sm font-medium">
            <span className="block text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Case Type</span>
            <select
              value={caseType}
              onChange={(event) => setCaseType(event.target.value as "Normal Case" | "BT Case")}
              className="block w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-slate-950 focus:border-blue-600 focus:outline-none focus:ring-1 focus:ring-blue-600 shadow-sm cursor-pointer"
            >
              <option>Normal Case</option>
              <option>BT Case</option>
            </select>
          </label>

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

function escapeControlCharacters(jsonString: string): string {
  // Matches string literals in JSON (enclosed in double quotes, handling escaped quotes)
  return jsonString.replace(/"([^"\\]|\\.)*"/g, (match) => {
    // Escape control characters inside matched string literal values
    return match.replace(/[\x00-\x1f]/g, (char) => {
      if (char === "\n") return "\\n";
      if (char === "\r") return "\\r";
      if (char === "\t") return "\\t";
      // Convert other control characters to standard Unicode escape sequence \u00xx
      const hex = char.charCodeAt(0).toString(16).padStart(4, "0");
      return "\\u" + hex;
    });
  });
}

function getSanitizedManifest(text: string): string {
  const trimmed = text.trim();
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      JSON.parse(escapeControlCharacters(trimmed));
      return escapeControlCharacters(trimmed);
    } catch {
      // The backend has a tolerant company-dump adapter for smart quotes,
      // truncated braces, and other non-standard database output.
      return trimmed;
    }
  }
  return trimmed;
}

function inferDocumentType(filename: string): string {
  const lower = filename.toLowerCase().replace(/\\/g, "/");

  if (lower.includes("pan")) {
    return "PAN Card";
  }
  if (lower.includes("aadhar") || lower.includes("aadhaar") || lower.includes("uidai")) {
    return "Aadhaar Card";
  }
  if (lower.includes("passport")) {
    return "Passport";
  }
  if (
    lower.includes("driving") ||
    lower.includes("dl ") ||
    lower.includes(" licence") ||
    lower.includes(" license")
  ) {
    return "Driving License";
  }
  if (lower.includes("voter") || lower.includes("epic")) {
    return "Voter ID";
  }
  if (lower.includes("cheque") || lower.includes("check")) {
    return "Cheque";
  }
  if (
    lower.includes("statement") ||
    lower.includes("bank_stmt") ||
    lower.includes("bank stmt") ||
    lower.includes("bankstmt")
  ) {
    return "Bank Statement";
  }
  if (
    lower.includes("utility") ||
    lower.includes("bill") ||
    lower.includes("electricity") ||
    lower.includes("water") ||
    lower.includes("gas_bill")
  ) {
    return "Utility Bill";
  }
  if (lower.includes("sanction") || lower.includes("loan_sanction")) {
    return "Sanction Letter";
  }
  if (lower.includes("agreement") || lower.includes("contract") || lower.includes("loan_agreement")) {
    return "Loan Agreement";
  }
  if (
    lower.includes("salary") ||
    lower.includes("pay slip") ||
    lower.includes("payslip") ||
    lower.includes("salary_slip")
  ) {
    return "Salary Slip";
  }
  if (lower.includes("kfs") || lower.includes("key fact")) {
    return "KFS (Key Fact Statement)";
  }

  // If there's a parent folder name, format and use it
  const parts = lower.split("/");
  if (parts.length > 1) {
    const parentFolder = parts[parts.length - 2];
    return parentFolder
      .replace(/[_-]/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase());
  }

  // Otherwise, clean up the file name (without extension)
  const baseName = parts[parts.length - 1].replace(/\.[^/.]+$/, "");
  return baseName
    .replace(/[_-]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
