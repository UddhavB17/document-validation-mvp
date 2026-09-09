"use client";

import { Fragment, useMemo, useState } from "react";

import { statusLabels } from "@/components/applications/reviewUtils";
import type { ApplicationReview, FieldComparison } from "@/lib/api";
import { displayValue, isSensitiveFieldName, maskSensitiveValue } from "@/components/applications/reviewUtils";

type ExtractedField = {
  id: string;
  person: string;
  document: string;
  fieldName: string;
  label: string;
  expectedValue: string | null;
  extractedValue: unknown;
  status: FieldComparison["status"];
  sourcePages: number[];
};

const PAGE_SIZE = 50;
const MAX_SOURCE_PAGES = 12;

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

export function buildExtractedGroups(data: ApplicationReview): ExtractedField[] {
  const pagesByNumber = new Map<number, ApplicationReview["pages"][number]>();
  data.pages.forEach((page) => {
    if (typeof page.page_number === "number") {
      pagesByNumber.set(page.page_number, page);
    }
  });

  const fields: ExtractedField[] = [];
  const comparisonKeys = new Set<string>();
  const addComparisonField = (person: string, field: FieldComparison) => {
    const key = `${person}::${field.field_name}`;
    comparisonKeys.add(key);
    fields.push({
      id: `comparison-${key}`,
      person,
      document: getDocumentLabel(field.source_pages, pagesByNumber),
      fieldName: field.field_name,
      label: field.label,
      expectedValue: field.expected_value,
      extractedValue: field.extracted_value,
      status: field.status,
      sourcePages: field.source_pages,
    });
  };

  (data.comparison_matrix?.core_parameters ?? []).forEach((field) => addComparisonField("Application", field));
  (data.comparison_matrix?.applicants ?? []).forEach((applicant) => {
    applicant.fields.forEach((field) => addComparisonField(applicant.person_name, field));
  });

  data.pages.forEach((page) => {
    const pageNumber = typeof page.page_number === "number" ? page.page_number : null;
    const document = String(page.document_type || "Unknown document");
    const person = getPagePerson(page.extracted_fields, data);
    Object.entries(page.extracted_fields ?? {}).forEach(([fieldName, value]) => {
      if (fieldName.startsWith("_") || !hasValue(value) || comparisonKeys.has(`${person}::${fieldName}`)) {
        return;
      }
      fields.push({
        id: `page-${pageNumber ?? "unknown"}-${document}-${fieldName}`,
        person,
        document,
        fieldName,
        label: formatFieldLabel(fieldName),
        expectedValue: null,
        extractedValue: value,
        status: "match",
        sourcePages: pageNumber ? [pageNumber] : [],
      });
    });
  });

  return fields.sort((left, right) => {
    const groupResult = `${left.person}\u0000${left.document}`.localeCompare(`${right.person}\u0000${right.document}`);
    return groupResult || left.label.localeCompare(right.label);
  });
}

export function ExtractedDataTab({
  data,
  onSelectPage,
}: {
  data: ApplicationReview;
  onSelectPage?: (pageNo: number, title: string, reason: string) => void;
}) {
  const [view, setView] = useState<"issues" | "all">("issues");
  const [showSensitive, setShowSensitive] = useState(false);
  const [page, setPage] = useState(1);
  const extractedFields = useMemo(() => buildExtractedGroups(data), [data]);
  const filteredFields = useMemo(
    () => extractedFields.filter((field) => view === "all" || isFieldIssue(field)),
    [extractedFields, view],
  );
  const pageCount = Math.max(1, Math.ceil(filteredFields.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const visibleFields = filteredFields.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  return (
    <section className="min-w-0 space-y-5">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="font-serif text-[16px] font-semibold text-[#16202E]">Extracted data</h2>
          <p className="mt-1 max-w-3xl text-[12.5px] font-medium leading-relaxed text-[#5C6B7A]">
            Review extracted values grouped by person, document, and field. Mismatches and missing values are shown first; internal pipeline keys are excluded.
          </p>
        </div>
        <label className="flex cursor-pointer items-center gap-2 text-xs font-bold text-[#5C6B7A]">
          <input
            type="checkbox"
            checked={showSensitive}
            onChange={(event) => setShowSensitive(event.target.checked)}
            className="h-4 w-4 rounded border-slate-300 text-[#2B4C7E] focus:ring-[#2B4C7E]/20"
          />
          Show sensitive values
        </label>
      </div>

      <div className="flex min-w-0 flex-wrap items-center justify-between gap-3 rounded-xl border border-[#E1E5EB] bg-[#F6F7FA]/70 p-3">
        <div className="flex flex-wrap gap-2" role="group" aria-label="Extracted data filter">
          <button
            type="button"
            onClick={() => { setView("issues"); setPage(1); }}
            className={`rounded-lg border px-3 py-1.5 text-xs font-bold transition-colors ${view === "issues" ? "border-[#2B4C7E] bg-[#EAF0F8] text-[#2B4C7E]" : "border-[#E1E5EB] bg-white text-[#5C6B7A] hover:bg-slate-50"}`}
          >
            Mismatches &amp; missing ({extractedFields.filter(isFieldIssue).length})
          </button>
          <button
            type="button"
            onClick={() => { setView("all"); setPage(1); }}
            className={`rounded-lg border px-3 py-1.5 text-xs font-bold transition-colors ${view === "all" ? "border-[#2B4C7E] bg-[#EAF0F8] text-[#2B4C7E]" : "border-[#E1E5EB] bg-white text-[#5C6B7A] hover:bg-slate-50"}`}
          >
            All extracted fields ({extractedFields.length})
          </button>
        </div>
        <span className="text-xs font-semibold text-[#5C6B7A]">Showing {filteredFields.length === 0 ? 0 : (currentPage - 1) * PAGE_SIZE + 1}–{Math.min(currentPage * PAGE_SIZE, filteredFields.length)} of {filteredFields.length}</span>
      </div>

      {visibleFields.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[#E1E5EB] bg-slate-50 p-7 text-center text-sm font-medium text-[#5C6B7A]">
          {view === "issues" ? "No mismatches or missing extracted values were found." : "No extracted fields were returned for this application."}
          {view === "issues" && extractedFields.length > 0 ? (
            <button type="button" onClick={() => { setView("all"); setPage(1); }} className="mt-3 block w-full text-xs font-bold text-[#2B4C7E] hover:underline">
              Show all extracted fields
            </button>
          ) : null}
        </div>
      ) : (
        <div className="min-w-0 max-w-full overflow-x-auto rounded-xl border border-[#E1E5EB] bg-white shadow-3xs">
          <table className="min-w-[850px] w-full border-collapse text-left text-[13px]">
            <thead className="bg-[#F6F7FA] text-[10px] uppercase tracking-wider text-[#5C6B7A]">
              <tr className="border-b border-[#E1E5EB]">
                <th className="px-3.5 py-3 font-bold">Person</th>
                <th className="px-3.5 py-3 font-bold">Document</th>
                <th className="px-3.5 py-3 font-bold">Field</th>
                <th className="px-3.5 py-3 font-bold">Expected</th>
                <th className="px-3.5 py-3 font-bold">Extracted</th>
                <th className="px-3.5 py-3 font-bold">Status</th>
                <th className="px-3.5 py-3 font-bold">Evidence</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#E1E5EB] text-[#16202E]">
              {visibleFields.map((field, index) => {
                const previous = visibleFields[index - 1];
                const startsGroup = !previous || previous.person !== field.person || previous.document !== field.document;
                const sensitive = isSensitiveFieldName(field.fieldName) || isSensitiveFieldName(field.label);
                const expected = sensitive && !showSensitive ? maskSensitiveValue(field.expectedValue) : displayValue(field.expectedValue);
                const extracted = sensitive && !showSensitive ? maskSensitiveValue(field.extractedValue) : displayValue(field.extractedValue);
                const missing = !hasValue(field.extractedValue);
                return (
                  <Fragment key={field.id}>
                    {startsGroup ? (
                      <tr className="bg-[#F6F7FA]/60">
                        <td colSpan={7} className="px-3.5 py-2 text-[10px] font-extrabold uppercase tracking-wider text-[#2B4C7E]">
                          {field.person} <span className="px-1 text-[#5C6B7A]">/</span> {field.document}
                        </td>
                      </tr>
                    ) : null}
                    <tr className="align-top hover:bg-slate-50/60">
                      <td className="px-3.5 py-3 font-semibold">{field.person}</td>
                      <td className="px-3.5 py-3 text-[#5C6B7A]">{field.document}</td>
                      <td className="px-3.5 py-3 font-semibold">{field.label}</td>
                      <td className="max-w-[180px] whitespace-pre-wrap break-words px-3.5 py-3 font-mono text-[11px] text-[#5C6B7A]">{expected}</td>
                      <td className={`max-w-[220px] whitespace-pre-wrap break-words px-3.5 py-3 font-mono text-[11px] ${missing ? "italic text-[#AF3B2E]" : "text-[#16202E]"}`}>
                        {missing ? "— Missing —" : extracted}
                      </td>
                      <td className="px-3.5 py-3">
                        <span className={`stamp rotate-0 ${missing || field.status === "mismatch" ? "mismatch" : field.status === "attention" ? "attention" : "match"}`}>
                          {missing ? "Missing" : statusLabels[field.status]}
                        </span>
                      </td>
                      <td className="px-3.5 py-3">
                        <div className="flex max-w-[190px] flex-wrap gap-1.5">
                          {field.sourcePages.slice(0, MAX_SOURCE_PAGES).map((pageNumber) => (
                            <button
                              key={pageNumber}
                              type="button"
                              disabled={!onSelectPage}
                              onClick={() => onSelectPage?.(pageNumber, field.label, `Evidence review for ${field.label}`)}
                              className="rounded-md border border-blue-200 bg-blue-50 px-2 py-1 font-mono text-[10px] font-bold text-[#2B4C7E] transition-colors hover:bg-blue-100 disabled:cursor-default disabled:opacity-70"
                            >
                              Page {pageNumber}
                            </button>
                          ))}
                          {field.sourcePages.length > MAX_SOURCE_PAGES ? <span className="px-1 py-1 text-[10px] font-semibold text-[#5C6B7A]">+{field.sourcePages.length - MAX_SOURCE_PAGES}</span> : null}
                          {field.sourcePages.length === 0 ? <span className="text-xs text-[#5C6B7A]">—</span> : null}
                        </div>
                      </td>
                    </tr>
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {filteredFields.length > PAGE_SIZE ? (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#E1E5EB] pt-4">
          <button type="button" disabled={currentPage === 1} onClick={() => setPage((value) => Math.max(1, value - 1))} className="rounded-lg border border-[#E1E5EB] bg-white px-3 py-2 text-xs font-bold text-[#2B4C7E] disabled:cursor-not-allowed disabled:text-slate-400">← Previous</button>
          <span className="text-xs font-semibold text-[#5C6B7A]">Page {currentPage} of {pageCount} · 50 rows per page</span>
          <button type="button" disabled={currentPage === pageCount} onClick={() => setPage((value) => Math.min(pageCount, value + 1))} className="rounded-lg border border-[#E1E5EB] bg-white px-3 py-2 text-xs font-bold text-[#2B4C7E] disabled:cursor-not-allowed disabled:text-slate-400">Next →</button>
        </div>
      ) : null}
    </section>
  );
}

function getDocumentLabel(
  sourcePages: number[],
  pagesByNumber: Map<number, ApplicationReview["pages"][number]>,
): string {
  const documents = Array.from(new Set(sourcePages.map((pageNumber) => String(pagesByNumber.get(pageNumber)?.document_type || "Unknown document"))));
  return documents.length > 0 ? documents.join(", ") : "No source document";
}

function getPagePerson(fields: Record<string, unknown> | undefined, data: ApplicationReview): string {
  const role = String(fields?._resolved_person_id || fields?._person_id || fields?._applicant_role || "").toLowerCase();
  if (role === "primary") {
    return String(data.application.applicant_name || data.ground_truth.applicant_name || "Primary applicant");
  }
  if (role === "coapplicant" || role === "co_applicant" || role === "guarantor") {
    return role === "guarantor" ? "Guarantor" : "Co-applicant";
  }
  return "Page-level extraction";
}

function isFieldIssue(field: ExtractedField): boolean {
  return field.status !== "match" || !hasValue(field.extractedValue);
}

function hasValue(value: unknown): boolean {
  return value !== null && value !== undefined && (typeof value !== "string" || value.trim().length > 0);
}

function formatFieldLabel(fieldName: string): string {
  return fieldName.replace(/_/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
}
