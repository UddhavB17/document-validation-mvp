import { StatusBadge } from "@/components/StatusBadge";
import { ZipDocument } from "@/lib/api";
import { inferDocumentType } from "@/lib/uploadUtils";

export function ZipDocumentInventory({ documents }: { documents: ZipDocument[] }) {
  return (
    <div className="space-y-3">
      <h3 className="text-sm font-bold text-slate-800">Source Files Inventory</h3>
      <div className="overflow-x-auto rounded-xl border border-[#E1E5EB] bg-white shadow-3xs">
        <table className="min-w-full divide-y divide-[#E1E5EB] text-left text-xs">
          <thead className="bg-[#F6F7FA] font-bold uppercase tracking-wider text-[#5C6B7A]">
            <tr>
              <th className="px-4 py-3 border-b border-[#E1E5EB]">ID</th>
              <th className="px-4 py-3 border-b border-[#E1E5EB]">Filename</th>
              <th className="px-4 py-3 border-b border-[#E1E5EB]">Inferred Document</th>
              <th className="px-4 py-3 border-b border-[#E1E5EB]">Format</th>
              <th className="px-4 py-3 border-b border-[#E1E5EB]">Worksheets</th>
              <th className="px-4 py-3 border-b border-[#E1E5EB]">Page Ranges</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#E1E5EB] text-[#16202E]">
            {documents.map((doc) => (
              <tr key={doc.source_document_id} className="hover:bg-slate-50/50 transition-colors duration-100 font-semibold">
                <td className="px-4 py-3 font-mono text-[#2B4C7E] font-bold">{doc.source_document_id}</td>
                <td className="px-4 py-3 font-semibold">{doc.original_filename}</td>
                <td className="px-4 py-3 font-semibold text-slate-800">
                  <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-[#EAF0F8] text-[#2B4C7E] border border-[#E1E5EB]">
                    {inferDocumentType(doc.original_filename)}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <StatusBadge status={doc.file_type} />
                </td>
                <td className="px-4 py-3 text-[#5C6B7A] font-medium">{doc.worksheets?.join(", ") || "-"}</td>
                <td className="px-4 py-3 font-mono font-bold text-slate-800">
                  {doc.internal_page_start === doc.internal_page_end
                    ? doc.internal_page_start
                    : `${doc.internal_page_start} - ${doc.internal_page_end}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-[#5C6B7A] font-medium leading-relaxed">
        * Note: The internal page numbers correspond to the consolidated PDF page layout for verification matches.
      </p>
    </div>
  );
}
