"use client";

import { FormEvent, useEffect, useState } from "react";

import { ErrorMessage } from "@/components/Message";
import { Metric } from "@/components/Metric";
import { api, UploadResponse, ZipPreparationProgress } from "@/lib/api";

import { SelectField } from "./UploadField";
import { ZipDocumentInventory } from "./ZipDocumentInventory";
import { ZipPreparationProgress as ZipPreparationProgressPanel } from "./ZipPreparationProgress";
import { CASE_TYPE_OPTIONS, getCaseType, getFormError, getSanitizedManifest } from "./uploadUtils";
import { useZipPreparation } from "./useZipPreparation";
import { CaseType, UploadFormProps } from "./types";

const manifestTemplate = (packageId: string) => ({
  schema_version: "1.0",
  loan_id: "LN-" + packageId.slice(0, 6).toUpperCase(),
  people: {
    primary: {
      applicant_name: "Ramesh Kumar",
      pan_number: "ABCDE1234F",
      aadhaar_number: "123456789012",
    },
  },
  document_index: [],
});

export function ZipPackageForm({ onUploaded }: UploadFormProps) {
  const [file, setFile] = useState<File | null>(null);
  const [preparingPackageId, setPreparingPackageId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isPreparing, setIsPreparing] = useState(false);
  const [isVerifying, setIsVerifying] = useState(false);
  const [manifestText, setManifestText] = useState("");
  const [caseType, setCaseType] = useState<CaseType>("Normal Case");
  const { progress, pollError } = useZipPreparation(preparingPackageId);

  useEffect(() => {
    if (pollError) {
      setError(pollError);
      setIsPreparing(false);
      setPreparingPackageId(null);
    }
  }, [pollError]);

  useEffect(() => {
    if (!progress) return;
    if (progress.status === "failed") {
      setError(progress.error || "ZIP preparation failed");
      setIsPreparing(false);
      setPreparingPackageId(null);
      return;
    }
    if (progress.status === "prepared" && preparingPackageId) {
      setIsPreparing(false);
      setManifestText(JSON.stringify(manifestTemplate(preparingPackageId), null, 2));
    }
  }, [preparingPackageId, progress]);

  async function handlePrepare(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setError("Please select a ZIP file");
      return;
    }
    setError(null);
    setIsPreparing(true);
    try {
      const result = await api.prepareZipPackage(file);
      setPreparingPackageId(result.package_id);
    } catch (preparationError) {
      setError(getFormError(preparationError));
      setIsPreparing(false);
    }
  }

  async function handleVerify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!preparingPackageId) return;
    setError(null);
    setIsVerifying(true);
    try {
      const manifest = getSanitizedManifest(manifestText);
      const result: UploadResponse = await api.verifyZipPackage(preparingPackageId, manifest, caseType);
      onUploaded(result);
    } catch (verificationError) {
      setError(getFormError(verificationError));
    } finally {
      setIsVerifying(false);
    }
  }

  function resetPackage() {
    setPreparingPackageId(null);
    setFile(null);
  }

  return (
    <div className="space-y-6">
      {error ? <ErrorMessage message={error} /> : null}

      {!progress || progress.status !== "prepared" ? (
        <PrepareZipStep file={file} isPreparing={isPreparing} progress={progress} onFileChange={setFile} onSubmit={handlePrepare} />
      ) : (
        <VerifyZipStep
          caseType={caseType}
          isVerifying={isVerifying}
          manifestText={manifestText}
          progress={progress}
          onCaseTypeChange={setCaseType}
          onManifestChange={setManifestText}
          onReset={resetPackage}
          onSubmit={handleVerify}
        />
      )}
    </div>
  );
}

function PrepareZipStep({
  file,
  isPreparing,
  progress,
  onFileChange,
  onSubmit,
}: {
  file: File | null;
  isPreparing: boolean;
  progress: ZipPreparationProgress | null;
  onFileChange: (file: File | null) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <form onSubmit={onSubmit} className="space-y-5 max-w-xl">
      <div className="space-y-2">
        <h2 className="font-serif text-[16px] font-bold text-[#16202E] border-b border-slate-100 pb-2 mb-2">Step 1: Upload and Prepare ZIP Folder</h2>
        <p className="text-xs text-[#5C6B7A] font-medium leading-relaxed">
          Upload the original ZIP package. Spreadsheets (.xlsx) are automatically rendered to readable PDF sheets, and images (.jpg/.png) are consolidated.
        </p>
      </div>
      <label className="block">
        <span className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">Intake ZIP Archive</span>
        <input
          className="block w-full text-sm text-slate-500 file:mr-4 file:py-2.5 file:px-4 file:rounded-lg file:border border-[#E1E5EB] bg-white file:text-xs file:font-semibold file:bg-[#F6F7FA] file:text-slate-700 hover:file:bg-slate-100 file:cursor-pointer rounded-lg px-4 py-2.5 focus:outline-none"
          type="file"
          accept=".zip,application/zip"
          onChange={(fileEvent) => onFileChange(fileEvent.target.files?.[0] ?? null)}
        />
      </label>
      <button
        type="submit"
        disabled={isPreparing || !file}
        className="px-5 py-2.5 text-sm font-semibold rounded-lg bg-[#2B4C7E] hover:bg-[#1E3559] text-white transition-all duration-150 shadow-3xs disabled:bg-slate-200 disabled:text-slate-500 cursor-pointer border-none"
      >
        {isPreparing ? "Preparing ZIP Archive..." : "Extract ZIP and Build Page Inventory"}
      </button>

      {isPreparing && progress ? <ZipPreparationProgressPanel progress={progress} /> : null}
    </form>
  );
}

function VerifyZipStep({
  caseType,
  isVerifying,
  manifestText,
  progress,
  onCaseTypeChange,
  onManifestChange,
  onReset,
  onSubmit,
}: {
  caseType: CaseType;
  isVerifying: boolean;
  manifestText: string;
  progress: ZipPreparationProgress;
  onCaseTypeChange: (caseType: CaseType) => void;
  onManifestChange: (manifest: string) => void;
  onReset: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <form onSubmit={onSubmit} className="space-y-6">
      <div className="flex justify-between items-center border-b border-[#E1E5EB] pb-3">
        <h2 className="font-serif text-[16px] font-bold text-[#16202E]">Step 2: Review Inventory &amp; Mapped Verification</h2>
        <button type="button" onClick={onReset} className="text-xs font-bold text-[#2B4C7E] hover:underline flex items-center gap-1 border-none bg-transparent cursor-pointer">
          Upload another ZIP
        </button>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <Metric label="Package ID" value={progress.package_id.slice(0, 8)} />
        <Metric label="Source files" value={progress.total_files} />
        <Metric label="Internal pages" value={progress.total_pages} />
      </div>

      {progress.documents ? <ZipDocumentInventory documents={progress.documents} /> : null}

      <div className="space-y-2">
        <label className="block text-sm font-bold text-[#16202E]">
          Trusted JSON or Raw Company Database Dump for this ZIP
          <span className="block font-normal text-xs text-[#5C6B7A] mt-1">Supply the JSON manifest or paste the raw text output from the database application.</span>
        </label>
        <textarea
          value={manifestText}
          onChange={(event) => onManifestChange(event.target.value)}
          className="h-80 w-full rounded-lg border border-[#E1E5EB] bg-white px-4 py-3 font-mono text-sm text-[#16202E] placeholder-slate-400 focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs"
          placeholder="Paste manifest or database dump here..."
        />
      </div>

      <label className="block max-w-sm text-sm font-medium">
        <span className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">Case Type</span>
        <select
          value={caseType}
          onChange={(event) => onCaseTypeChange(getCaseType(event.target.value))}
          className="block w-full rounded-lg border border-[#E1E5EB] bg-white px-3 py-2.5 text-[#16202E] focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs cursor-pointer text-sm font-medium"
        >
          {CASE_TYPE_OPTIONS.map((option) => <option key={option}>{option}</option>)}
        </select>
      </label>

      <button type="submit" disabled={isVerifying} className="px-5 py-2.5 text-sm font-semibold rounded-lg bg-[#2B4C7E] hover:bg-[#1E3559] text-white transition-all duration-150 shadow-3xs disabled:bg-slate-200 disabled:text-slate-500 border-none cursor-pointer">
        {isVerifying ? "Verifying..." : "Identify and Verify ZIP Documents"}
      </button>
    </form>
  );
}
