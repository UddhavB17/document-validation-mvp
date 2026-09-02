"use client";

import { FormEvent, useEffect, useState } from "react";

import { ErrorMessage } from "@/components/Message";
import { Metric } from "@/components/Metric";
import { ZipDocumentInventory } from "@/components/upload/ZipDocumentInventory";
import { ZipPreparationProgressPanel } from "@/components/upload/ZipPreparationProgress";
import { api, UploadResponse, ZipPreparationProgress } from "@/lib/api";
import { CaseType } from "@/lib/types";
import { formError, getSanitizedManifest } from "@/lib/uploadUtils";

const POLL_INTERVAL_MS = 2000;

function buildManifestTemplate(packageId: string): string {
  const template = {
    schema_version: "1.0",
    loan_id: `LN-${packageId.slice(0, 6).toUpperCase()}`,
    people: {
      primary: {
        applicant_name: "Ramesh Kumar",
        pan_number: "ABCDE1234F",
        aadhaar_number: "123456789012",
      },
    },
    document_index: [],
  };
  return JSON.stringify(template, null, 2);
}

/**
 * ZIP intake state machine:
 * 1. User selects a file and starts preparation (POST /upload/package).
 * 2. Poll preparation progress until status is "prepared" or "failed".
 * 3. On success, show inventory + manifest editor for verification (POST verify).
 */
export function useZipPackageUpload() {
  const [file, setFile] = useState<File | null>(null);
  const [preparingPackageId, setPreparingPackageId] = useState<string | null>(null);
  const [progress, setProgress] = useState<ZipPreparationProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isPreparing, setIsPreparing] = useState(false);
  const [isVerifying, setIsVerifying] = useState(false);
  const [manifestText, setManifestText] = useState("");
  const [caseType, setCaseType] = useState<CaseType>("Normal Case");

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
            setManifestText(buildManifestTemplate(preparingPackageId));
          }
        }
      } catch (err) {
        if (!active) return;
        clearInterval(interval);
        setIsPreparing(false);
        setError(formError(err));
        setPreparingPackageId(null);
      }
    }, POLL_INTERVAL_MS);

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
    } catch (err) {
      setError(formError(err));
      setIsPreparing(false);
    }
  }

  async function handleVerify(event: FormEvent, onUploaded: (result: UploadResponse) => void) {
    event.preventDefault();
    if (!preparingPackageId) return;
    setError(null);
    setIsVerifying(true);
    try {
      const manifest = getSanitizedManifest(manifestText);
      const res = await api.verifyZipPackage(preparingPackageId, manifest, caseType);
      onUploaded(res);
    } catch (err) {
      setError(formError(err));
    } finally {
      setIsVerifying(false);
    }
  }

  function resetUpload() {
    setProgress(null);
    setPreparingPackageId(null);
    setFile(null);
    setManifestText("");
    setError(null);
  }

  return {
    file,
    setFile,
    progress,
    error,
    isPreparing,
    isVerifying,
    manifestText,
    setManifestText,
    caseType,
    setCaseType,
    handlePrepare,
    handleVerify,
    resetUpload,
  };
}

export function ZipPackageForm({ onUploaded }: { onUploaded: (result: UploadResponse) => void }) {
  const zip = useZipPackageUpload();
  const isPrepared = zip.progress?.status === "prepared";

  return (
    <div className="space-y-6">
      {zip.error ? <ErrorMessage message={zip.error} /> : null}

      {!isPrepared ? (
        <form onSubmit={zip.handlePrepare} className="space-y-5 max-w-xl">
          <div className="space-y-2">
            <h2 className="font-serif text-[16px] font-bold text-[#16202E] border-b border-slate-100 pb-2 mb-2">
              Step 1: Upload and Prepare ZIP Folder
            </h2>
            <p className="text-xs text-[#5C6B7A] font-medium leading-relaxed">
              Upload the original ZIP package. Spreadsheets (.xlsx) are automatically rendered to readable PDF sheets, and
              images (.jpg/.png) are consolidated.
            </p>
          </div>
          <label className="block">
            <span className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">Intake ZIP Archive</span>
            <input
              className="block w-full text-sm text-slate-500 file:mr-4 file:py-2.5 file:px-4 file:rounded-lg file:border border-[#E1E5EB] bg-white file:text-xs file:font-semibold file:bg-[#F6F7FA] file:text-slate-700 hover:file:bg-slate-100 file:cursor-pointer rounded-lg px-4 py-2.5 focus:outline-none"
              type="file"
              accept=".zip,application/zip"
              onChange={(e) => zip.setFile(e.target.files?.[0] || null)}
            />
          </label>
          <button
            type="submit"
            disabled={zip.isPreparing || !zip.file}
            className="px-5 py-2.5 text-sm font-semibold rounded-lg bg-[#2B4C7E] hover:bg-[#1E3559] text-white transition-all duration-150 shadow-3xs disabled:bg-slate-200 disabled:text-slate-500 cursor-pointer border-none"
          >
            {zip.isPreparing ? "Preparing ZIP Archive..." : "Extract ZIP and Build Page Inventory"}
          </button>

          {zip.isPreparing && zip.progress ? <ZipPreparationProgressPanel progress={zip.progress} /> : null}
        </form>
      ) : (
        <form onSubmit={(event) => zip.handleVerify(event, onUploaded)} className="space-y-6">
          <div className="flex justify-between items-center border-b border-[#E1E5EB] pb-3">
            <h2 className="font-serif text-[16px] font-bold text-[#16202E]">Step 2: Review Inventory & Mapped Verification</h2>
            <button
              type="button"
              onClick={zip.resetUpload}
              className="text-xs font-bold text-[#2B4C7E] hover:underline flex items-center gap-1 border-none bg-transparent cursor-pointer"
            >
              Upload another ZIP
            </button>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <Metric label="Package ID" value={zip.progress!.package_id.slice(0, 8)} />
            <Metric label="Source files" value={zip.progress!.total_files ?? 0} />
            <Metric label="Internal pages" value={zip.progress!.total_pages ?? 0} />
          </div>

          {zip.progress?.documents ? <ZipDocumentInventory documents={zip.progress.documents} /> : null}

          <div className="space-y-2">
            <label className="block text-sm font-bold text-[#16202E]">
              Trusted JSON or Raw Company Database Dump for this ZIP
              <span className="block font-normal text-xs text-[#5C6B7A] mt-1">
                Supply the JSON manifest or paste the raw text output from the database application.
              </span>
            </label>
            <textarea
              value={zip.manifestText}
              onChange={(e) => zip.setManifestText(e.target.value)}
              className="h-80 w-full rounded-lg border border-[#E1E5EB] bg-white px-4 py-3 font-mono text-sm text-[#16202E] placeholder-slate-400 focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs"
              placeholder="Paste manifest or database dump here..."
            />
          </div>

          <label className="block max-w-sm text-sm font-medium">
            <span className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">Case Type</span>
            <select
              value={zip.caseType}
              onChange={(event) => zip.setCaseType(event.target.value as CaseType)}
              className="block w-full rounded-lg border border-[#E1E5EB] bg-white px-3 py-2.5 text-[#16202E] focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs cursor-pointer text-sm font-medium"
            >
              <option>Normal Case</option>
              <option>BT Case</option>
            </select>
          </label>

          <button
            type="submit"
            disabled={zip.isVerifying}
            className="px-5 py-2.5 text-sm font-semibold rounded-lg bg-[#2B4C7E] hover:bg-[#1E3559] text-white transition-all duration-150 shadow-3xs disabled:bg-slate-200 disabled:text-slate-500 border-none cursor-pointer"
          >
            {zip.isVerifying ? "Verifying..." : "Identify and Verify ZIP Documents"}
          </button>
        </form>
      )}
    </div>
  );
}
