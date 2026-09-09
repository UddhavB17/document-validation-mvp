"use client";

import { useState } from "react";

import { PageHeader } from "@/components/PageHeader";
import { UploadResultSummary } from "@/components/upload/UploadResultSummary";
import { UploadResponse } from "@/lib/api";

import { MappedUploadForm } from "@/components/upload/MappedUploadForm";
import { PartnerJsonForm } from "@/components/upload/PartnerJsonForm";
import { PdfUploadForm } from "@/components/upload/PdfUploadForm";
import { UploadTabs } from "@/components/upload/UploadTabs";
import { UploadTab } from "@/components/upload/types";
import { ZipPackageForm } from "@/components/upload/ZipPackageForm";

export default function UploadPage() {
  const [activeTab, setActiveTab] = useState<UploadTab>("pdf");
  const [result, setResult] = useState<UploadResponse | null>(null);

  return (
    <div className="space-y-6 max-w-[1600px] mx-auto">
      <PageHeader
        title="Document Intake"
        description="Upload a loan-file packet, watch page results finish, then review the final checklist output."
      />
      <UploadTabs activeTab={activeTab} onChange={setActiveTab} />

      <div className="bg-white border border-[#E1E5EB] rounded-2xl p-6 shadow-2xs">
        {activeTab === "pdf" ? <PdfUploadForm onUploaded={setResult} /> : null}
        {activeTab === "mapped" ? <MappedUploadForm onUploaded={setResult} /> : null}
        {activeTab === "json" ? <PartnerJsonForm onUploaded={setResult} /> : null}
        {activeTab === "zip" ? <ZipPackageForm onUploaded={setResult} /> : null}
      </div>

      {result ? <UploadResultSummary result={result} /> : null}
    </div>
  );
}
