import { StatusBadge } from "@/components/StatusBadge";
import { ZipDocument } from "@/lib/api";
import { inferDocumentType } from "./uploadUtils";

export function ZipDocumentInventory({ documents }: { documents: ZipDocument[] }) {
  return (
    <div className="space-y-3">
      <h3 className="text-sm font-bold text-slate-800">Source Files Inventory</h3>
      <div className="overflow-x-auto rounded-xl border border-[#E1E5EB] bg-white shadow-3xs">
        <table className="min-w-full divide-y divide-[#E1E5EB] text-left text-xs">
          <caption className="sr-only">Original files found in the ZIP package and their consolidated page ranges</caption>
          <thead className="bg-[#F6F7FA] font-bold uppercase tracking-wider text-[#5C6B7A]">
            <tr>
              <th scope="col" className="px-4 py-3 border-b border-[#E1E5EB]">ID</th>
              <th scope="col" className="px-4 py-3 border-b border-[#E1E5EB]">Filename</th>
              <th scope="col" className="px-4 py-3 border-b border-[#E1E5EB]">Inferred Document</th>
              <th scope="col" className="px-4 py-3 border-b border-[#E1E5EB]">Format</th>
              <th scope="col" className="px-4 py-3 border-b border-[#E1E5EB]">Worksheets</th>
              <th scope="col" className="px-4 py-3 border-b border-[#E1E5EB]">Page Ranges</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#E1E5EB] text-[#16202E]">
            {documents.map((document) => (
              <tr key={document.source_document_id} className="hover:bg-slate-50/50 transition-colors duration-100 font-semibold">
                <td className="px-4 py-3 font-mono text-[#2B4C7E] font-bold">{document.source_document_id}</td>
                <td className="px-4 py-3 font-semibold">{document.original_filename}</td>
                <td className="px-4 py-3 font-semibold text-slate-800">
                  <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-[#EAF0F8] text-[#2B4C7E] border border-[#E1E5EB]">{inferDocumentType(document.original_filename)}</span>
                </td>
                <td className="px-4 py-3"><StatusBadge status={document.file_type} /></td>
                <td className="px-4 py-3 text-[#5C6B7A] font-medium">{document.worksheets?.join(", ") || "-"}</td>
                <td className="px-4 py-3 font-mono font-bold text-slate-800">
                  {document.internal_page_start === document.internal_page_end ? document.internal_page_start : `${document.internal_page_start} - ${document.internal_page_end}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-[#5C6B7A] font-medium leading-relaxed">* Note: The internal page numbers correspond to the consolidated PDF page layout for verification matches.</p>
    </div>
  );
}
