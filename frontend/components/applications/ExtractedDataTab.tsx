import { ApplicationReview } from "@/lib/api";

export function buildExtractedByDoc(data: ApplicationReview): Record<string, Record<string, unknown>> {
  const extractedByDoc: Record<string, Record<string, unknown>> = {};
  data.pages.forEach((p) => {
    const docType = String(p.document_type || "Unknown Document");
    const fields = p.extracted_fields || {};
    const cleanFields: Record<string, unknown> = {};
    Object.entries(fields).forEach(([k, v]) => {
      if (!k.startsWith("_") && v !== null && v !== undefined && String(v).trim()) {
        cleanFields[k] = v;
      }
    });

    if (Object.keys(cleanFields).length > 0) {
      if (!extractedByDoc[docType]) {
        extractedByDoc[docType] = {};
      }
      extractedByDoc[docType] = {
        ...extractedByDoc[docType],
        ...cleanFields,
      };
    }
  });
  return extractedByDoc;
}

export function ExtractedDataTab({ data }: { data: ApplicationReview }) {
  const extractedByDoc = buildExtractedByDoc(data);

  return (
    <div className="space-y-6">
      <h2 className="font-serif text-[16px] font-semibold mb-1">Extracted fields — raw output</h2>
      <p className="text-[#5C6B7A] text-[12.5px] mb-4 font-medium">What DMEF read off each document. No expected-value comparison here — see Anomalies &amp; Flags for that.</p>

      {Object.keys(extractedByDoc).length === 0 ? (
        <div className="bg-slate-50 border border-[#E1E5EB] rounded-xl p-6 text-center text-[#5C6B7A] italic">
          No raw extracted parameters found in processed pages.
        </div>
      ) : (
        Object.entries(extractedByDoc).map(([docType, fields]) => (
          <div key={docType} className="bg-white border border-[#E1E5EB] rounded-xl p-4.5 shadow-3xs mb-4 last:mb-0">
            <h3 className="text-[13.5px] font-bold text-[#16202E] border-b border-slate-100 pb-2 mb-3 font-serif uppercase tracking-wider">{docType}</h3>
            <table className="w-full text-[13px] border-collapse">
              <tbody className="divide-y divide-slate-100 font-semibold text-[#16202E]">
                {Object.entries(fields).map(([k, v]) => (
                  <tr key={k}>
                    <td className="py-2.5 text-[#5C6B7A] font-medium w-1/3 truncate">{k.replace(/_/g, " ")}</td>
                    <td className="py-2.5 font-mono text-[12px] select-all break-all">{String(v)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))
      )}
    </div>
  );
}
