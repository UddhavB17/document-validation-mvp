"use client";

import { useState } from "react";

import { PageHeader } from "@/components/PageHeader";
import { MappedUploadForm } from "@/components/upload/MappedUploadForm";
import { PartnerJsonForm } from "@/components/upload/PartnerJsonForm";
import { PdfUploadForm } from "@/components/upload/PdfUploadForm";
import { UploadResultSummary } from "@/components/upload/UploadResultSummary";
import { UploadTabBar } from "@/components/upload/UploadTabBar";
import { ZipPackageForm } from "@/components/upload/ZipPackageForm";
import { UploadResponse } from "@/lib/api";
import { UploadTab } from "@/lib/types";

export default function UploadPage() {
  const [tab, setTab] = useState<UploadTab>("pdf");
  const [result, setResult] = useState<UploadResponse | null>(null);

  return (
    <div className="space-y-6 max-w-[1600px] mx-auto">
      <PageHeader
        title="Document Intake"
        description="Upload a loan-file packet, watch page results finish, then review the final checklist output."
      />

      {/* Tab routing picks which intake flow to show; each form reports back via onUploaded. */}
      <UploadTabBar activeTab={tab} onTabChange={setTab} />

      <div className="bg-white border border-[#E1E5EB] rounded-2xl p-6 shadow-2xs">
        {tab === "pdf" ? <PdfUploadForm onUploaded={setResult} /> : null}
        {tab === "mapped" ? <MappedUploadForm onUploaded={setResult} /> : null}
        {tab === "json" ? <PartnerJsonForm onUploaded={setResult} /> : null}
        {tab === "zip" ? <ZipPackageForm onUploaded={setResult} /> : null}
      </div>

      {result ? <UploadResultSummary result={result} /> : null}
    </div>
  );
}
