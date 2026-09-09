"use client";

import { ALL_FIELD_SCHEMAS } from "./fieldSchemas";

interface RequiredFieldsMatrixProps {
  getValue: (key: string) => string;
  updateSetting: (key: string, value: string) => Promise<void>;
}

export function RequiredFieldsMatrix({ getValue, updateSetting }: RequiredFieldsMatrixProps) {
  function handleFieldToggle(docKey: string, fieldName: string, currentlyRequired: boolean) {
    const fieldsList = parseStringList(getValue(`required_fields.${docKey}`));
    const updatedFields = currentlyRequired
      ? fieldsList.filter((field) => field !== fieldName)
      : [...fieldsList, fieldName];
    void updateSetting(`required_fields.${docKey}`, JSON.stringify(updatedFields));
  }

  return (
    <div className="rounded-xl border border-[#E1E5EB] bg-white p-6 shadow-2xs animate-fade-in">
      <h2 className="mb-2 text-base font-bold font-serif text-[#16202E]">📋 Document Verification Fields Matrix</h2>
      <p className="text-xs text-[#5C6B7A] mb-6 font-semibold leading-relaxed">Toggle which specific fields are required to pass validation checklist for each document type.</p>

      <div className="space-y-6">
        {Object.entries(ALL_FIELD_SCHEMAS).map(([docKey, schema]) => {
          const enabledFields = parseStringList(getValue(`required_fields.${docKey}`));
          return (
            <div key={docKey} className="border-b border-slate-100 pb-4 last:border-0 last:pb-0">
              <h3 className="text-sm font-semibold text-slate-800 mb-2">{schema.label}</h3>
              <div className="flex flex-wrap gap-4">
                {schema.fields.map((field) => {
                  const isRequired = enabledFields.includes(field);
                  return (
                    <label key={field} className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-semibold cursor-pointer transition-colors ${isRequired ? "bg-[#EAF0F8] border-[#2B4C7E] text-[#2B4C7E]" : "bg-[#F6F7FA] border-[#E1E5EB] text-[#5C6B7A] hover:bg-slate-50"}`}>
                      <input type="checkbox" checked={isRequired} onChange={() => handleFieldToggle(docKey, field, isRequired)} className="sr-only" />
                      <span className="font-mono text-[11.5px]">{field}</span>
                      {isRequired ? <span className="text-[10px] text-[#2B4C7E]">✓</span> : null}
                    </label>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function parseStringList(value: string): string[] {
  try {
    const parsed: unknown = JSON.parse(value);
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
}
