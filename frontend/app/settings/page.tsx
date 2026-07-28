"use client";

import { useEffect, useState } from "react";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

interface Setting {
  config_key: string;
  config_value: string;
  value_type: string;
  category: string;
  label: string;
  description: string;
}

// Map of all possible fields for each document type to render in the Matrix
// Map of all possible fields for each document type to render in the Matrix
const DEFAULT_FIELD_SCHEMAS: Record<string, { label: string; fields: string[] }> = {
  pan: {
    label: "PAN Card",
    fields: ["pan_number", "applicant_name", "date_of_birth"],
  },
  aadhaar: {
    label: "Aadhaar Card",
    fields: ["aadhaar_number", "applicant_name", "date_of_birth", "address", "pin_code"],
  },
  voter_id: {
    label: "Voter ID",
    fields: ["voter_id_number", "applicant_name", "date_of_birth", "address"],
  },
  driving_license: {
    label: "Driving License",
    fields: ["dl_number", "applicant_name", "date_of_birth", "validity_date", "is_expired"],
  },
  passport: {
    label: "Passport",
    fields: ["passport_number", "applicant_name", "date_of_birth", "expiry_date", "nationality"],
  },
  mnrega_job_card: {
    label: "MNREGA Job Card",
    fields: ["job_card_number", "applicant_name", "date_of_birth", "address"],
  },
  npr_letter: {
    label: "NPR Letter",
    fields: ["npr_number", "applicant_name", "date_of_birth", "address"],
  },
  form_97: {
    label: "Form 97",
    fields: ["applicant_name", "declaration_date"],
  },
  kfs: {
    label: "KFS",
    fields: ["applicant_name", "loan_amount", "tenure", "roi", "emi"],
  },
  sanction_letter: {
    label: "Sanction Letter",
    fields: ["applicant_name", "loan_amount", "tenure", "roi", "emi"],
  },
  facility_agreement: {
    label: "Facility Agreement",
    fields: ["applicant_name", "loan_amount", "tenure", "roi", "emi", "agreement_date"],
  },
  loan_agreement: {
    label: "Loan Agreement",
    fields: ["applicant_name", "loan_amount", "tenure", "roi", "emi", "agreement_date"],
  },
  stamp_duty: {
    label: "Stamp Duty",
    fields: ["stamp_duty_amount", "stamp_paper_number", "first_party", "second_party"],
  },
  insurance_consent: {
    label: "Insurance Consent",
    fields: ["is_consent_given", "premium_amount"],
  },
  cibil_report: {
    label: "CIBIL Report",
    fields: ["applicant_name", "credit_score"],
  },
  crif_report: {
    label: "CRIF Report",
    fields: ["applicant_name", "credit_score"],
  },
  bank_statement: {
    label: "Bank Statement",
    fields: ["applicant_name", "account_number", "ifsc"],
  },
  passbook: {
    label: "Passbook",
    fields: ["applicant_name", "account_number", "ifsc"],
  },
  cheque: {
    label: "Cheque / Cancelled Cheque",
    fields: ["applicant_name", "account_number", "cheque_number", "ifsc", "is_cancelled"],
  },
  salary_slip: {
    label: "Salary Slip",
    fields: ["applicant_name", "salary_month", "net_salary"],
  },
  clearance_report: {
    label: "Clearance Report (CERSAI)",
    fields: ["search_result", "debtor_name", "pan_number"],
  },
  nach_form: {
    label: "NACH Form",
    fields: ["account_number", "ifsc", "mandate_limit"],
  },
  utility_bill: {
    label: "Utility Bill",
    fields: ["applicant_name", "address", "pin_code"],
  },
  application_form: {
    label: "Application Form",
    fields: ["applicant_name", "pan_number", "aadhaar_number", "date_of_birth", "phone_number", "address", "pin_code", "loan_amount"],
  },
  property_document: {
    label: "Property Document",
    fields: ["property_address", "owner_name", "registration_date"],
  },
  deed: {
    label: "Deed",
    fields: ["first_party", "second_party", "deed_type", "registration_date"],
  },
  affidavit: {
    label: "Affidavit",
    fields: ["applicant_name", "declaration_text"],
  },
  death_certificate: {
    label: "Death Certificate",
    fields: ["deceased_name", "date_of_death"],
  },
  divorce_decree: {
    label: "Divorce Decree",
    fields: ["husband_name", "wife_name", "decree_date"],
  },
  noc: {
    label: "NOC",
    fields: ["applicant_name", "issue_date", "noc_type"],
  },
  pdc: {
    label: "PDC",
    fields: ["account_holder_name", "cheque_number", "bank_name"],
  },
  cam: {
    label: "CAM",
    fields: ["applicant_name", "recommended_loan_amount", "tenure"],
  },
};

export default function SettingsPage() {
  const [settings, setSettings] = useState<Setting[]>([]);
  const [activeTab, setActiveTab] = useState<"general" | "fields">("general");
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // API Key raw states for local edits
  const [llmApiKeyInput, setLlmApiKeyInput] = useState("");
  const [ocrApiKeyInput, setOcrApiKeyInput] = useState("");

  // Fields Matrix navigation states
  const [selectedDocType, setSelectedDocType] = useState<string>("pan");
  const [docSearchQuery, setDocSearchQuery] = useState<string>("");
  const [newFieldName, setNewFieldName] = useState<string>("");

  useEffect(() => {
    fetchSettings();
  }, []);

  const fetchSettings = async () => {
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE_URL}/settings`);
      if (res.ok) {
        const data = await res.json();
        setSettings(data);
        const llmKeyObj = data.find((s: Setting) => s.config_key === "llm_api_key");
        const ocrKeyObj = data.find((s: Setting) => s.config_key === "ocr_api_key");
        if (llmKeyObj) setLlmApiKeyInput(llmKeyObj.config_value);
        if (ocrKeyObj) setOcrApiKeyInput(ocrKeyObj.config_value);
      }
    } catch (e) {
      console.error("Failed to load settings:", e);
    } finally {
      setLoading(false);
    }
  };

  const updateSingleSetting = async (key: string, newValue: string) => {
    try {
      setSavingKey(key);
      const res = await fetch(`${API_BASE_URL}/settings/${key}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config_value: newValue }),
      });
      if (res.ok) {
        const resData = await res.json();
        const updatedVal = resData.config_value;
        setSettings((prev) =>
          prev.map((s) => (s.config_key === key ? { ...s, config_value: updatedVal } : s))
        );
        if (key === "llm_api_key") setLlmApiKeyInput(updatedVal);
        if (key === "ocr_api_key") setOcrApiKeyInput(updatedVal);
        showToast("Setting updated successfully!");
      }
    } catch (e) {
      console.error("Failed to update setting:", e);
    } finally {
      setSavingKey(null);
    }
  };

  const showToast = (msg: string) => {
    setSuccessMessage(msg);
    setTimeout(() => setSuccessMessage(null), 3000);
  };

  // Helper getters/setters for specific settings keys
  const getVal = (key: string) => settings.find((s) => s.config_key === key)?.config_value ?? "";

  const renderGeneralSettings = () => {
    const isLlmEnabled = getVal("llm_enabled") === "true";
    const provider = getVal("llm_provider");
    const model = getVal("llm_model");
    const minConfidence = parseFloat(getVal("min_confidence") || "0.70");

    const isLlmApiKeyEnabled = getVal("llm_api_key_enabled") === "true";
    const isOcrApiKeyEnabled = getVal("ocr_api_key_enabled") === "true";

    return (
      <div className="space-y-8">
        {/* Classification Settings */}
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="mb-4 text-lg font-semibold text-slate-900 flex items-center gap-2">
            ⚙️ Classification Settings
          </h2>
          <div className="space-y-6">
            <div>
              <label className="block text-sm font-medium text-slate-700">
                Minimum Classification Confidence
              </label>
              <p className="text-xs text-slate-500 mb-2">
                Raise or lower the minimum score required to auto-classify pages. Currently recommended: 0.70.
              </p>
              <div className="flex items-center gap-4">
                <input
                  type="range"
                  min="0.4"
                  max="0.95"
                  step="0.05"
                  value={minConfidence}
                  onChange={(e) => updateSingleSetting("min_confidence", e.target.value)}
                  className="h-2 w-64 cursor-pointer appearance-none rounded-lg bg-slate-200 accent-blue-600"
                />
                <span className="text-sm font-semibold text-slate-800">{minConfidence}</span>
              </div>
            </div>
          </div>
        </div>

        {/* LLM Validation Settings */}
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="mb-4 text-lg font-semibold text-slate-900 flex items-center gap-2">
            🤖 LLM Verification Settings
          </h2>
          <div className="space-y-6">
            <div className="flex items-start justify-between">
              <div>
                <label className="text-sm font-medium text-slate-700 block">
                  Enable LLM Verification checks
                </label>
                <span className="text-xs text-slate-500 block">
                  Toggle dynamic validation checks & checklist evaluations via LLM.
                </span>
              </div>
              <button
                type="button"
                onClick={() => updateSingleSetting("llm_enabled", isLlmEnabled ? "false" : "true")}
                className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                  isLlmEnabled ? "bg-blue-600" : "bg-slate-200"
                }`}
              >
                <span
                  className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                    isLlmEnabled ? "translate-x-5" : "translate-x-0"
                  }`}
                />
              </button>
            </div>

            {isLlmEnabled && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-4 border-t border-slate-100">
                <div>
                  <label className="block text-sm font-medium text-slate-700">LLM Provider</label>
                  <select
                    value={provider}
                    onChange={(e) => updateSingleSetting("llm_provider", e.target.value)}
                    className="mt-1 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none"
                  >
                    <option value="ollama">Ollama (Local)</option>
                    <option value="openai">OpenAI</option>
                    <option value="gemini">Gemini</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700">Model Name</label>
                  <input
                    type="text"
                    value={model}
                    onChange={(e) => {}}
                    onBlur={(e) => updateSingleSetting("llm_model", e.target.value)}
                    placeholder="e.g. qwen2.5:7b-instruct-q4_0"
                    className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none"
                  />
                  <span className="text-[10px] text-slate-400">Press enter or focus out to save</span>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* API Key Configuration */}
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="mb-4 text-lg font-semibold text-slate-900 flex items-center gap-2">
            🔑 API Key Settings
          </h2>
          <div className="space-y-6">
            {/* LLM API Key */}
            <div className="border-b border-slate-100 pb-6">
              <div className="flex items-start justify-between mb-4">
                <div>
                  <label className="text-sm font-medium text-slate-700 block">
                    Enable LLM API Key Usage
                  </label>
                  <span className="text-xs text-slate-500 block">
                    Use custom API Key for the cloud LLM provider (will not reveal key once saved).
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => updateSingleSetting("llm_api_key_enabled", isLlmApiKeyEnabled ? "false" : "true")}
                  className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                    isLlmApiKeyEnabled ? "bg-blue-600" : "bg-slate-200"
                  }`}
                >
                  <span
                    className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                      isLlmApiKeyEnabled ? "translate-x-5" : "translate-x-0"
                    }`}
                  />
                </button>
              </div>

              {isLlmApiKeyEnabled && (
                <div>
                  <label className="block text-sm font-medium text-slate-700">LLM API Key</label>
                  <input
                    type="password"
                    value={llmApiKeyInput}
                    onChange={(e) => setLlmApiKeyInput(e.target.value)}
                    onBlur={() => updateSingleSetting("llm_api_key", llmApiKeyInput)}
                    placeholder="Enter your LLM API Key"
                    className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none"
                  />
                  <span className="text-[10px] text-slate-400">Press enter or focus out to save</span>
                </div>
              )}
            </div>

            {/* OCR API Key */}
            <div>
              <div className="flex items-start justify-between mb-4">
                <div>
                  <label className="text-sm font-medium text-slate-700 block">
                    Enable OCR API Key Usage
                  </label>
                  <span className="text-xs text-slate-500 block">
                    Use custom API Key for the cloud OCR service (will not reveal key once saved).
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => updateSingleSetting("ocr_api_key_enabled", isOcrApiKeyEnabled ? "false" : "true")}
                  className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                    isOcrApiKeyEnabled ? "bg-blue-600" : "bg-slate-200"
                  }`}
                >
                  <span
                    className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                      isOcrApiKeyEnabled ? "translate-x-5" : "translate-x-0"
                    }`}
                  />
                </button>
              </div>

              {isOcrApiKeyEnabled && (
                <div>
                  <label className="block text-sm font-medium text-slate-700">OCR API Key</label>
                  <input
                    type="password"
                    value={ocrApiKeyInput}
                    onChange={(e) => setOcrApiKeyInput(e.target.value)}
                    onBlur={() => updateSingleSetting("ocr_api_key", ocrApiKeyInput)}
                    placeholder="Enter your OCR API Key"
                    className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none"
                  />
                  <span className="text-[10px] text-slate-400">Press enter or focus out to save</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  };

  const handleFieldToggle = (docKey: string, fieldName: string, currentlyRequired: boolean) => {
    const configKey = `required_fields.${docKey}`;
    const rawVal = getVal(configKey);
    let fieldsList: string[] = [];
    try {
      if (rawVal) {
        fieldsList = JSON.parse(rawVal);
      }
    } catch (e) {
      // fallback
    }

    let updatedFields: string[];
    if (currentlyRequired) {
      updatedFields = fieldsList.filter((f) => f !== fieldName);
    } else {
      updatedFields = Array.from(new Set([...fieldsList, fieldName]));
    }
    updateSingleSetting(configKey, JSON.stringify(updatedFields));
  };

  const renderFieldsMatrix = () => {
    const docEntries = Object.entries(DEFAULT_FIELD_SCHEMAS);
    const filteredDocs = docEntries.filter(([docKey, schema]) =>
      schema.label.toLowerCase().includes(docSearchQuery.toLowerCase()) ||
      docKey.toLowerCase().includes(docSearchQuery.toLowerCase())
    );

    const schema = DEFAULT_FIELD_SCHEMAS[selectedDocType] || { label: selectedDocType, fields: [] };
    const rawVal = getVal(`required_fields.${selectedDocType}`);
    let enabledFields: string[] = [];
    try {
      if (rawVal) {
        enabledFields = JSON.parse(rawVal);
      }
    } catch (e) {
      // fallback
    }

    const combinedFields = Array.from(new Set([...schema.fields, ...enabledFields]));

    const handleAddField = () => {
      const cleanField = newFieldName.trim().toLowerCase().replace(/\s+/g, "_");
      if (!cleanField) return;
      if (combinedFields.includes(cleanField)) {
        showToast("Field already exists!");
        return;
      }
      const updatedFields = [...enabledFields, cleanField];
      updateSingleSetting(`required_fields.${selectedDocType}`, JSON.stringify(updatedFields));
      setNewFieldName("");
      showToast(`Added field "${cleanField}" to ${schema.label}!`);
    };

    return (
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Left Column: Supported Documents list */}
        <div className="lg:col-span-1 rounded-xl border border-slate-200 bg-white p-4 shadow-sm h-[calc(100vh-280px)] flex flex-col min-h-[400px]">
          <h2 className="text-sm font-semibold text-slate-900 mb-3 flex items-center gap-1.5">
            📄 Supported Documents
          </h2>
          
          <input
            type="text"
            placeholder="Search documents..."
            value={docSearchQuery}
            onChange={(e) => setDocSearchQuery(e.target.value)}
            className="w-full mb-3 rounded-lg border border-slate-300 px-3 py-1.5 text-xs focus:border-blue-500 focus:outline-none"
          />

          <div className="flex-1 overflow-y-auto space-y-1 pr-1">
            {filteredDocs.map(([docKey, docSchema]) => {
              const isActive = selectedDocType === docKey;
              const hasConfig = getVal(`required_fields.${docKey}`) !== "";
              return (
                <button
                  key={docKey}
                  onClick={() => setSelectedDocType(docKey)}
                  className={`w-full text-left px-3 py-2 rounded-lg text-xs font-medium transition-colors flex items-center justify-between ${
                    isActive
                      ? "bg-blue-600 text-white shadow-sm font-semibold"
                      : "text-slate-700 hover:bg-slate-100"
                  }`}
                >
                  <span className="truncate">{docSchema.label}</span>
                  {hasConfig && (
                    <span className={`w-1.5 h-1.5 rounded-full ${isActive ? "bg-white animate-pulse" : "bg-blue-500"}`} />
                  )}
                </button>
              );
            })}
            {filteredDocs.length === 0 && (
              <div className="text-center py-8 text-xs text-slate-400">No documents found</div>
            )}
          </div>
        </div>

        {/* Right Column: Fields Checklist & Add Custom Field Form */}
        <div className="lg:col-span-3 rounded-xl border border-slate-200 bg-white p-6 shadow-sm flex flex-col justify-between min-h-[400px]">
          <div>
            <div className="border-b border-slate-100 pb-4 mb-4">
              <h2 className="text-lg font-semibold text-slate-900">{schema.label} Verification Fields</h2>
              <p className="text-xs text-slate-500 mt-1">
                Toggle required fields to check for borrower information validation. Checkboxes mark fields required.
              </p>
            </div>

            {/* Custom Field Input Form */}
            <div className="bg-slate-50 p-4 rounded-xl mb-6 border border-slate-100">
              <label className="block text-xs font-semibold text-slate-700 mb-2">
                ➕ Add New Custom Scope of Search (Required Field)
              </label>
              <div className="flex gap-3">
                <input
                  type="text"
                  placeholder="e.g. father_name, registration_no, pin_code"
                  value={newFieldName}
                  onChange={(e) => setNewFieldName(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleAddField(); }}
                  className="flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs shadow-sm focus:border-blue-500 focus:outline-none"
                />
                <button
                  onClick={handleAddField}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold rounded-lg shadow-sm transition-colors"
                >
                  Add Field
                </button>
              </div>
              <p className="text-[10px] text-slate-400 mt-1.5">
                Note: Custom fields will be dynamically extracted from document OCR text.
              </p>
            </div>

            {/* Fields List */}
            <div className="space-y-3">
              <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider">Required Fields Matrix</h3>
              {combinedFields.length > 0 ? (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  {combinedFields.map((field) => {
                    const isRequired = enabledFields.includes(field);
                    return (
                      <label
                        key={field}
                        className={`flex items-center justify-between p-3 rounded-xl border text-xs font-medium cursor-pointer transition-all shadow-sm ${
                          isRequired
                            ? "bg-blue-50 border-blue-200 text-blue-700 font-semibold"
                            : "bg-slate-50 border-slate-100 text-slate-600 hover:bg-slate-100"
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            checked={isRequired}
                            onChange={() => handleFieldToggle(selectedDocType, field, isRequired)}
                            className="rounded border-slate-300 text-blue-600 focus:ring-blue-500 w-4 h-4 cursor-pointer"
                          />
                          <span className="font-mono">{field}</span>
                        </div>
                        {isRequired && <span className="text-xs text-blue-500 font-semibold">✓</span>}
                      </label>
                    );
                  })}
                </div>
              ) : (
                <div className="text-center py-12 text-xs text-slate-400 border border-dashed border-slate-200 rounded-xl bg-slate-25">
                  No verification fields set. Use the form above to add search fields.
                </div>
              )}
            </div>
          </div>

          <div className="mt-8 pt-4 border-t border-slate-100 flex justify-between items-center text-[10px] text-slate-400">
            <span>Database Configuration: <code>required_fields.{selectedDocType}</code></span>
            <span>Total Fields Configured: {enabledFields.length}</span>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">System settings</h1>
          <p className="text-sm text-slate-500">Configure OCR, LLM, and document field verification parameters.</p>
        </div>
        {successMessage && (
          <div className="rounded-lg bg-green-50 px-4 py-2 text-sm font-medium text-green-700 border border-green-200 animate-pulse">
            {successMessage}
          </div>
        )}
      </div>

      <div className="flex gap-2 border-b border-slate-200">
        <button
          onClick={() => setActiveTab("general")}
          className={`pb-3 text-sm font-semibold border-b-2 px-4 transition-colors ${
            activeTab === "general"
              ? "border-blue-600 text-blue-600"
              : "border-transparent text-slate-500 hover:text-slate-700"
          }`}
        >
          General Configuration
        </button>
        <button
          onClick={() => setActiveTab("fields")}
          className={`pb-3 text-sm font-semibold border-b-2 px-4 transition-colors ${
            activeTab === "fields"
              ? "border-blue-600 text-blue-600"
              : "border-transparent text-slate-500 hover:text-slate-700"
          }`}
        >
          Required Fields Matrix
        </button>
      </div>

      {loading ? (
        <div className="text-center py-12 text-slate-500">Loading settings...</div>
      ) : activeTab === "general" ? (
        renderGeneralSettings()
      ) : (
        renderFieldsMatrix()
      )}
    </div>
  );
}
