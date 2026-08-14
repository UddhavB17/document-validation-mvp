"use client";

import React from "react";

interface FieldComparison {
  field_name: string;
  label: string;
  expected_value: string | null;
  extracted_value: string | null;
  status: "match" | "mismatch" | "attention";
  source_pages: number[];
}

interface ApplicantComparison {
  applicant_role: "primary" | "co_applicant" | "guarantor";
  applicant_label: string;
  person_name: string;
  fields: FieldComparison[];
}

interface ComparisonTableProps {
  coreParameters?: FieldComparison[] | null;
  applicants?: ApplicantComparison[] | null;
  onSelectPage: (pageNo: number, title: string, reason: string) => void;
}

const statusLabels = {
  match: "Match",
  mismatch: "Mismatch",
  attention: "Attention",
};

export default function ComparisonTable({ coreParameters, applicants, onSelectPage }: ComparisonTableProps) {
  const coreParams = coreParameters || [];
  const applicantList = applicants || [];

  // Calculate counts for summary strip
  const allFields = [...coreParams, ...applicantList.flatMap(a => a.fields)];
  const counts = { match: 0, mismatch: 0, attention: 0 };
  allFields.forEach(f => {
    if (counts[f.status] !== undefined) {
      counts[f.status]++;
    }
  });

  return (
    <div className="space-y-6 animate-fade-in">
      {/* 1. Comparison Summary Strip */}
      <div>
        <h2 className="font-serif text-base font-semibold text-[16px] mb-3">Comparison summary</h2>
        <div className="flex gap-3">
          <div className="flex-1 bg-white border border-[#E1E5EB] rounded-xl p-3.5 shadow-2xs">
            <div className="font-mono text-2xl font-semibold text-[#1F7A5C]">{counts.match}</div>
            <div className="text-[#5C6B7A] text-[11.5px] mt-1 font-semibold">Fields matched</div>
          </div>
          <div className="flex-1 bg-white border border-[#E1E5EB] rounded-xl p-3.5 shadow-2xs">
            <div className="font-mono text-2xl font-semibold text-[#AF3B2E]">{counts.mismatch}</div>
            <div className="text-[#5C6B7A] text-[11.5px] mt-1 font-semibold">Mismatches</div>
          </div>
          <div className="flex-1 bg-white border border-[#E1E5EB] rounded-xl p-3.5 shadow-2xs">
            <div className="font-mono text-2xl font-semibold text-[#A0701C]">{counts.attention}</div>
            <div className="text-[#5C6B7A] text-[11.5px] mt-1 font-semibold">Needs attention</div>
          </div>
        </div>
      </div>

      {/* 2. Core Parameters Table */}
      <div>
        <h2 className="font-serif text-base font-semibold text-[16px] mb-3">Core parameters</h2>
        <div className="bg-white border border-[#E1E5EB] rounded-xl overflow-hidden shadow-2xs p-1">
          <table className="w-full border-collapse text-left text-[13px]">
            <thead>
              <tr className="border-b border-[#E1E5EB]">
                <th className="text-[#5C6B7A] font-semibold text-[11px] uppercase tracking-wider px-3.5 py-2.5">Parameter</th>
                <th className="text-[#5C6B7A] font-semibold text-[11px] uppercase tracking-wider px-3.5 py-2.5">Expected</th>
                <th className="text-[#5C6B7A] font-semibold text-[11px] uppercase tracking-wider px-3.5 py-2.5">Extracted</th>
                <th className="text-[#5C6B7A] font-semibold text-[11px] uppercase tracking-wider px-3.5 py-2.5">Status</th>
                <th className="text-[#5C6B7A] font-semibold text-[11px] uppercase tracking-wider px-3.5 py-2.5">Source</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#E1E5EB] text-[#16202E]">
              {coreParams.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-3.5 py-4 text-center text-[#5C6B7A] italic">No core parameters available.</td>
                </tr>
              ) : (
                coreParams.map((param) => (
                  <tr key={param.field_name} className="hover:bg-slate-50/50 transition-colors duration-150">
                    <td className="px-3.5 py-3 font-semibold text-[#16202E]">{param.label}</td>
                    <td className="px-3.5 py-3 font-mono text-[12px]">{param.expected_value || "—"}</td>
                    <td className="px-3.5 py-3 font-mono text-[12px]">
                      {param.extracted_value ? (
                        param.extracted_value
                      ) : (
                        <span className="text-[#5C6B7A]/60 italic font-medium">— not extracted —</span>
                      )}
                    </td>
                    <td className="px-3.5 py-3">
                      <span className={`stamp ${param.status}`}>
                        {statusLabels[param.status]}
                      </span>
                    </td>
                    <td className="px-3.5 py-3">
                      <div className="flex flex-wrap gap-1.5">
                        {param.source_pages.length > 0 ? (
                          param.source_pages.map((p) => (
                            <button
                              key={p}
                              type="button"
                              onClick={() => onSelectPage(p, param.label, `Audit review for ${param.label}`)}
                              className="font-mono text-[11.5px] bg-[#EAF0F8] text-[#2B4C7E] border-none rounded-md px-2.5 py-1 font-semibold hover:bg-[#2B4C7E] hover:text-white transition-all cursor-pointer"
                            >
                              Page {p}
                            </button>
                          ))
                        ) : (
                          <span className="text-[#5C6B7A] font-medium">—</span>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* 3. Demographic Comparison Table Block */}
      <div>
        <h2 className="font-serif text-base font-semibold text-[16px] mb-3">Demographic comparison</h2>
        {applicantList.length === 0 ? (
          <div className="bg-white border border-[#E1E5EB] rounded-xl p-6 text-center text-[#5C6B7A] italic">
            No applicant demographic comparison available.
          </div>
        ) : (
          applicantList.map((applicant) => (
            <div key={applicant.person_name} className="mb-6 last:mb-0">
              {/* Section Header */}
              <div className="flex items-center gap-2 mb-2">
                <h3 className="font-serif text-[15px] font-semibold m-0">{applicant.person_name}</h3>
                <span className="text-[10px] font-semibold text-[#5C6B7A] bg-[#F6F7FA] border border-[#E1E5EB] px-2 py-0.5 rounded-full uppercase tracking-wider font-bold">
                  {applicant.applicant_label}
                </span>
              </div>

              {/* Table wrapper */}
              <div className="bg-white border border-[#E1E5EB] rounded-xl overflow-hidden shadow-2xs p-1">
                <table className="w-full border-collapse text-left text-[13px]">
                  <thead>
                    <tr className="border-b border-[#E1E5EB]">
                      <th className="text-[#5C6B7A] font-semibold text-[11px] uppercase tracking-wider px-3.5 py-2.5">Field</th>
                      <th className="text-[#5C6B7A] font-semibold text-[11px] uppercase tracking-wider px-3.5 py-2.5">Expected</th>
                      <th className="text-[#5C6B7A] font-semibold text-[11px] uppercase tracking-wider px-3.5 py-2.5">Extracted</th>
                      <th className="text-[#5C6B7A] font-semibold text-[11px] uppercase tracking-wider px-3.5 py-2.5">Status</th>
                      <th className="text-[#5C6B7A] font-semibold text-[11px] uppercase tracking-wider px-3.5 py-2.5">Source</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#E1E5EB] text-[#16202E]">
                    {applicant.fields.length === 0 ? (
                      <tr>
                        <td colSpan={5} className="px-3.5 py-4 text-center text-[#5C6B7A] italic">No demographic parameters extracted.</td>
                      </tr>
                    ) : (
                      applicant.fields.map((field) => (
                        <tr key={field.field_name} className="hover:bg-slate-50/50 transition-colors duration-150">
                          <td className="px-3.5 py-3 font-semibold text-[#16202E]">{field.label}</td>
                          <td className="px-3.5 py-3 font-mono text-[12px]">{field.expected_value || "—"}</td>
                          <td className="px-3.5 py-3 font-mono text-[12px]">
                            {field.extracted_value ? (
                              field.extracted_value
                            ) : (
                              <span className="text-[#5C6B7A]/60 italic font-medium">— not extracted —</span>
                            )}
                          </td>
                          <td className="px-3.5 py-3">
                            <span className={`stamp ${field.status}`}>
                              {statusLabels[field.status]}
                            </span>
                          </td>
                          <td className="px-3.5 py-3">
                            <div className="flex flex-wrap gap-1.5">
                              {field.source_pages.length > 0 ? (
                                field.source_pages.map((p) => (
                                  <button
                                    key={p}
                                    type="button"
                                    onClick={() => onSelectPage(p, `${applicant.person_name} — ${field.label}`, `Audit review for ${field.label}`)}
                                    className="font-mono text-[11.5px] bg-[#EAF0F8] text-[#2B4C7E] border-none rounded-md px-2.5 py-1 font-semibold hover:bg-[#2B4C7E] hover:text-white transition-all cursor-pointer"
                                  >
                                    Page {p}
                                  </button>
                                ))
                              ) : (
                                <span className="text-[#5C6B7A] font-medium">—</span>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
