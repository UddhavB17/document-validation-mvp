"use client";

import { useState } from "react";

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

  function changeTab(tab: UploadTab) {
    setActiveTab(tab);
    // A result belongs to the mode that produced it. Clear it when the
    // operator changes modes so a previous application is never mistaken for
    // the current intake flow.
    setResult(null);
  }

  return (
    <div className="space-y-6 max-w-[1600px] mx-auto">
      <PageHeader
        title="Document Intake"
        description="Prepare the original ZIP package, inspect its file inventory, then verify trusted data before processing."
      />
      <UploadTabs activeTab={activeTab} onChange={changeTab} />

      <div className="bg-white border border-[#E1E5EB] rounded-2xl p-6 shadow-2xs">
        {activeTab === "zip" ? (
          <section id="upload-panel-zip" role="tabpanel" aria-labelledby="upload-tab-zip">
            <ZipPackageForm onUploaded={setResult} />
          </section>
        ) : null}
        {activeTab === "mapped" ? (
          <section id="upload-panel-mapped" role="tabpanel" aria-labelledby="upload-tab-mapped">
            <MappedUploadForm onUploaded={setResult} />
          </section>
        ) : null}
      </div>

      {result ? <UploadResultSummary result={result} /> : null}
    </div>
  );
}
