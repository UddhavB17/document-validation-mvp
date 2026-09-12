"use client";

import { useRef, useState } from "react";

import { PageHeader } from "@/components/PageHeader";
import { UploadResultSummary } from "@/components/upload/UploadResultSummary";
import { UploadResponse } from "@/lib/api";

import { MappedUploadForm } from "@/components/upload/MappedUploadForm";
import { UploadTabs } from "@/components/upload/UploadTabs";
import { UploadTab } from "@/components/upload/types";
import { ZipPackageForm } from "@/components/upload/ZipPackageForm";

export default function UploadPage() {
  const [activeTab, setActiveTab] = useState<UploadTab>("zip");
  const [result, setResult] = useState<UploadResponse | null>(null);
  const [busyTabs, setBusyTabs] = useState<Record<UploadTab, boolean>>({ zip: false, mapped: false });
  const activeTabRef = useRef<UploadTab>("zip");

  function updateBusy(tab: UploadTab, busy: boolean) {
    setBusyTabs((current) => current[tab] === busy ? current : { ...current, [tab]: busy });
  }

  function changeTab(tab: UploadTab) {
    activeTabRef.current = tab;
    setActiveTab(tab);
    // A result belongs to the mode that produced it. Clear it when the
    // operator changes modes so a previous application is never mistaken for
    // the current intake flow.
    setResult(null);
  }

  function clearResultFor(tab: UploadTab) {
    if (activeTabRef.current === tab) {
      setResult(null);
    }
  }

  function showResultFor(tab: UploadTab, uploadResult: UploadResponse) {
    // A request can finish after its panel has been hidden. Do not display
    // that response in another intake mode.
    if (activeTabRef.current === tab) {
      setResult(uploadResult);
    }
  }

  return (
    <div className="space-y-6 max-w-[1600px] mx-auto">
      <PageHeader
        title="Document Intake"
        description="Prepare the original ZIP package, inspect its file inventory, then verify trusted data before processing."
      />

      <UploadTabs activeTab={activeTab} onChange={changeTab} disabled={busyTabs.zip || busyTabs.mapped} />

      {activeTab === "zip" ? <ol className="grid grid-cols-1 gap-3 rounded-xl border border-[#E1E5EB] bg-[#F6F7FA] p-4 text-xs font-medium text-[#5C6B7A] sm:grid-cols-3" aria-label="Document intake steps">
        <li className={activeTab === "zip" ? "font-bold text-[#2B4C7E]" : undefined}>
          <span className="mr-1 font-mono">1.</span> Prepare the original ZIP
        </li>
        <li className={activeTab === "zip" ? "font-bold text-[#2B4C7E]" : undefined}>
          <span className="mr-1 font-mono">2.</span> Inspect the source-file inventory
        </li>
        <li className={activeTab === "zip" ? "font-bold text-[#2B4C7E]" : undefined}>
          <span className="mr-1 font-mono">3.</span> Verify trusted data and submit
        </li>
      </ol> : null}

      <div className="bg-white border border-[#E1E5EB] rounded-2xl p-6 shadow-2xs">
        <section
          id="upload-panel-zip"
          role="tabpanel"
          aria-labelledby="upload-tab-zip"
          hidden={activeTab !== "zip"}
        >
          <ZipPackageForm
            onBusyChange={(busy) => updateBusy("zip", busy)}
            onFlowStart={() => clearResultFor("zip")}
            onUploaded={(uploadResult) => showResultFor("zip", uploadResult)}
          />
        </section>
        <section
          id="upload-panel-mapped"
          role="tabpanel"
          aria-labelledby="upload-tab-mapped"
          hidden={activeTab !== "mapped"}
        >
          <MappedUploadForm
            onBusyChange={(busy) => updateBusy("mapped", busy)}
            onFlowStart={() => clearResultFor("mapped")}
            onUploaded={(uploadResult) => showResultFor("mapped", uploadResult)}
          />
        </section>
      </div>

      {result ? <UploadResultSummary result={result} /> : null}
    </div>
  );
}
