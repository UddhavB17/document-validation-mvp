"use client";

import { FormEvent, RefObject, useEffect, useRef, useState } from "react";

import { ErrorMessage } from "@/components/Message";
import { Metric } from "@/components/Metric";
import { api, UploadResponse, ZipPreparationProgress } from "@/lib/api";

import { ZipDocumentInventory } from "./ZipDocumentInventory";
import { ZipPreparationProgress as ZipPreparationProgressPanel } from "./ZipPreparationProgress";
import { CASE_TYPE_OPTIONS, getCaseType, getFormError, getSanitizedManifest } from "./uploadUtils";
import { useZipPreparation } from "./useZipPreparation";
import { CaseType, UploadFormProps } from "./types";

export function ZipPackageForm({ onUploaded, onFlowStart, onBusyChange }: UploadFormProps) {
  const [file, setFile] = useState<File | null>(null);
  const [preparingPackageId, setPreparingPackageId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isPreparing, setIsPreparing] = useState(false);
  const [isVerifying, setIsVerifying] = useState(false);
  const [manifestText, setManifestText] = useState("");
  const [caseType, setCaseType] = useState<CaseType>("Normal Case");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { progress, pollError } = useZipPreparation(preparingPackageId);

  useEffect(() => {
    onBusyChange?.(isPreparing || isVerifying);
  }, [isPreparing, isVerifying, onBusyChange]);

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
    }
  }, [preparingPackageId, progress]);

  async function handlePrepare(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setError("Please select a ZIP file");
      return;
    }
    onFlowStart?.();
    setError(null);
    setPreparingPackageId(null);
    setIsPreparing(true);
    setIsVerifying(false);
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
    onFlowStart?.();
    setError(null);
    setIsVerifying(true);
    try {
      const manifest = getSanitizedManifest(manifestText);
      if (!manifest) {
        throw new Error("Trusted JSON or company database data is required");
      }
      const result: UploadResponse = await api.verifyZipPackage(preparingPackageId, manifest, caseType);
      onUploaded(result);
    } catch (verificationError) {
      setError(getFormError(verificationError));
    } finally {
      setIsVerifying(false);
    }
  }

  function resetPackage() {
    onFlowStart?.();
    setPreparingPackageId(null);
    setFile(null);
    setManifestText("");
    setError(null);
    setIsPreparing(false);
    setIsVerifying(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function selectFile(nextFile: File | null) {
    onFlowStart?.();
    setPreparingPackageId(null);
    setFile(nextFile);
    setManifestText("");
    setError(null);
    setIsPreparing(false);
    setIsVerifying(false);
  }

  const readyToVerify = Boolean(
    preparingPackageId && progress && progress.status === "prepared" && !isPreparing,
  );

  return (
    <div className="space-y-6">
      {error ? <ErrorMessage message={error} /> : null}

      {!readyToVerify || !progress ? (
        <PrepareZipStep
          file={file}
          fileInputRef={fileInputRef}
          isPreparing={isPreparing}
          progress={progress}
          onFileChange={selectFile}
          onSubmit={handlePrepare}
        />
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
  fileInputRef,
  isPreparing,
  progress,
  onFileChange,
  onSubmit,
}: {
  file: File | null;
  fileInputRef: RefObject<HTMLInputElement>;
  isPreparing: boolean;
  progress: ZipPreparationProgress | null;
  onFileChange: (file: File | null) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <form onSubmit={onSubmit} className="space-y-5 max-w-xl">
      <div className="space-y-2">
        <h2 className="font-serif text-[16px] font-bold text-[#16202E] border-b border-slate-100 pb-2 mb-2">Step 1: Prepare the original ZIP package</h2>
        <p className="text-xs text-[#5C6B7A] font-medium leading-relaxed">
          Upload the original ZIP package. The system keeps each source file boundary while preparing a page inventory. Spreadsheets (.xlsx) are rendered to readable PDF sheets, and images (.jpg/.png) are consolidated.
        </p>
      </div>
      <label className="block" htmlFor="zip-package-file">
        <span className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">Intake ZIP Archive</span>
        <input
          ref={fileInputRef}
          id="zip-package-file"
          className="block w-full text-sm text-slate-500 file:mr-4 file:py-2.5 file:px-4 file:rounded-lg file:border border-[#E1E5EB] bg-white file:text-xs file:font-semibold file:bg-[#F6F7FA] file:text-slate-700 hover:file:bg-slate-100 file:cursor-pointer rounded-lg px-4 py-2.5 focus:outline-none"
          type="file"
          accept=".zip,application/zip"
          disabled={isPreparing}
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

      {isPreparing ? (
        progress ? <ZipPreparationProgressPanel progress={progress} /> : <p className="text-sm font-medium text-[#5C6B7A]" role="status" aria-live="polite">Uploading ZIP package…</p>
      ) : null}
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
        <h2 className="font-serif text-[16px] font-bold text-[#16202E]">Step 2: Inspect the original-file inventory</h2>
        <button type="button" onClick={onReset} disabled={isVerifying} className="text-xs font-bold text-[#2B4C7E] hover:underline flex items-center gap-1 border-none bg-transparent cursor-pointer disabled:cursor-not-allowed disabled:text-slate-400">
          Upload another ZIP
        </button>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <Metric label="Package ID" value={progress.package_id.slice(0, 8)} />
        <Metric label="Source files" value={progress.total_files} />
        <Metric label="Internal pages" value={progress.total_pages} />
      </div>

      {progress.documents ? <ZipDocumentInventory documents={progress.documents} /> : null}

      <div className="space-y-2 border-t border-slate-100 pt-5">
        <h3 className="text-sm font-bold text-[#16202E]">Step 3: Verify trusted data</h3>
        <label className="block text-sm font-bold text-[#16202E]" htmlFor="zip-trusted-manifest">
          Trusted JSON or company database data for this ZIP
          <span id="zip-trusted-manifest-help" className="block font-normal text-xs text-[#5C6B7A] mt-1">Supply the JSON manifest or paste the raw text output from the trusted database application.</span>
        </label>
        <textarea
          id="zip-trusted-manifest"
          value={manifestText}
          onChange={(event) => onManifestChange(event.target.value)}
          aria-describedby="zip-trusted-manifest-help"
          aria-required="true"
          className="h-80 w-full rounded-lg border border-[#E1E5EB] bg-white px-4 py-3 font-mono text-sm text-[#16202E] placeholder-slate-400 focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs"
          placeholder="Paste the trusted manifest or database dump here..."
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
