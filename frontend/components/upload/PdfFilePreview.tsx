"use client";

import { useEffect, useState } from "react";

import { formatFileSize } from "@/lib/uploadUtils";

export function PdfFilePreview({ file, onRemove }: { file: File; onRemove: () => void }) {
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
    <div className="rounded-xl border border-[#EAF0F8] bg-[#EAF0F8]/30 p-4 shadow-3xs">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between font-semibold">
        <div className="min-w-0">
          <div className="text-[10px] font-extrabold uppercase tracking-wider text-[#2B4C7E]">Selected PDF</div>
          <div className="truncate text-sm font-bold text-[#16202E] leading-relaxed" title={file.name}>
            {file.name}
          </div>
          <div className="text-[11px] font-medium text-[#5C6B7A]">
            {formatFileSize(file.size)} · Opens locally in a new tab for confirmation
          </div>
        </div>
        <div className="flex shrink-0 gap-2 text-xs font-semibold">
          <button
            type="button"
            onClick={openPreview}
            disabled={!objectUrl}
            className="rounded-lg bg-[#2B4C7E] hover:bg-[#1E3559] px-4 py-2 font-bold text-white shadow-3xs disabled:bg-slate-200 disabled:text-slate-500 cursor-pointer border-none"
          >
            Open PDF Preview
          </button>
          <button
            type="button"
            onClick={onRemove}
            className="rounded-lg border border-[#E1E5EB] bg-white px-4 py-2 font-bold text-[#5C6B7A] hover:bg-slate-50 hover:text-[#16202E] cursor-pointer"
          >
            Remove
          </button>
        </div>
      </div>
      {previewError ? (
        <div className="mt-3 rounded-lg border border-[#AF3B2E] bg-[#FBEBE8] px-3 py-2 text-xs font-semibold text-[#AF3B2E]">
          {previewError}
        </div>
      ) : null}
    </div>
  );
}
