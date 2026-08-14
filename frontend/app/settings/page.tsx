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
  is_secret?: boolean;
  has_value?: boolean;
}

const ALL_FIELD_SCHEMAS: Record<string, { label: string; fields: string[] }> = {
  pan: {
    label: "PAN Card",
    fields: ["pan_number", "applicant_name", "dob"],
  },
  aadhaar: {
    label: "Aadhaar Card",
    fields: ["aadhaar_number", "applicant_name", "dob", "address", "pin_code"],
  },
  voter_id: {
    label: "Voter ID",
    fields: ["voter_id_number", "applicant_name", "dob", "address"],
  },
  driving_license: {
    label: "Driving License",
    fields: ["dl_number", "applicant_name", "dob", "validity_date", "is_expired"],
  },
  sanction_letter: {
    label: "Sanction Letter / KFS",
    fields: ["loan_amount", "tenure", "emi", "roi", "applicant_name"],
  },
  loan_agreement: {
    label: "Loan Agreement",
    fields: ["loan_amount", "tenure", "emi", "roi", "borrower_name", "agreement_date"],
  },
  cibil_report: {
    label: "CIBIL Report",
    fields: ["credit_score", "applicant_name", "report_date"],
  },
  crif_report: {
    label: "CRIF Report",
    fields: ["credit_score", "applicant_name", "report_date"],
  },
  bank_statement: {
    label: "Bank Statement",
    fields: ["account_holder_name", "account_number", "ifsc"],
  },
  passbook: {
    label: "Passbook",
    fields: ["account_holder_name", "account_number", "ifsc"],
  },
  cheque: {
    label: "Cheque / Cancelled Cheque",
    fields: ["account_holder_name", "account_number", "cheque_number", "ifsc", "is_cancelled"],
  },
  salary_slip: {
    label: "Salary Slip",
    fields: ["applicant_name", "salary_month", "net_salary"],
  },
  stamp_duty: {
    label: "Stamp Duty",
    fields: ["stamp_duty_amount", "stamp_paper_number", "first_party", "second_party"],
  },
  insurance_consent: {
    label: "Insurance Consent",
    fields: ["is_consent_given", "premium_amount"],
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
};

export default function SettingsPage() {
  const [settings, setSettings] = useState<Setting[]>([]);
  const [activeTab, setActiveTab] = useState<"general" | "fields">("general");
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [draftValues, setDraftValues] = useState<Record<string, string>>({});

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
      }
    } catch (e) {
      console.error("Failed to load settings:", e);
    } finally {
      setLoading(false);
    }
  };

  const updateSingleSetting = async (key: string, newValue: string, options?: { clearSecret?: boolean }) => {
    try {
      setSavingKey(key);
      const res = await fetch(`${API_BASE_URL}/settings/${key}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config_value: newValue, clear_secret: options?.clearSecret ?? false }),
      });
      if (res.ok) {
        const updated = await res.json();
        setSettings((prev) =>
          prev.map((s) => (s.config_key === key ? { ...s, ...updated } : s))
        );
        setDraftValues((prev) => ({ ...prev, [key]: "" }));
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

  const getSetting = (key: string) => settings.find((s) => s.config_key === key);
  const getVal = (key: string) => getSetting(key)?.config_value ?? "";

  const renderGeneralSettings = () => {
    const isLlmEnabled = getVal("llm_enabled") === "true";
    const provider = getVal("llm_provider");
    const model = getVal("llm_model");
    const minConfidence = parseFloat(getVal("min_confidence") || "0.70");
    const ocrProvider = getVal("ocr.provider") || "google_vision";
    const googleAuth = getVal("google.vision.auth") || "auto";
    const googleFeature = getVal("google.vision.feature") || "DOCUMENT_TEXT_DETECTION";
    const googleTimeout = getVal("google.vision.timeout.seconds") || "60";
    const googleLanguageHints =
      draftValues["google.vision.language_hints"] ?? getVal("google.vision.language_hints");
    const googleApiKey = getSetting("google.vision.api_key");
    const googleApiKeyDraft = draftValues["google.vision.api_key"] ?? "";
    const googleControlsVisible = ocrProvider === "google_vision" || ocrProvider === "auto";

    return (
      <div className="space-y-8 animate-fade-in">
        {/* Classification Settings */}
        <div className="rounded-xl border border-[#E1E5EB] bg-white p-6 shadow-2xs">
          <h2 className="mb-4 text-base font-bold font-serif text-[#16202E] flex items-center gap-2 border-b border-slate-50 pb-2">
            ⚙️ Classification Settings
          </h2>
          <div className="space-y-6">
            <div>
              <label className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-1">
                Minimum Classification Confidence
              </label>
              <p className="text-xs text-[#5C6B7A] mb-3 font-semibold leading-relaxed">
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
                  className="h-2 w-64 cursor-pointer appearance-none rounded-lg bg-slate-200 accent-[#2B4C7E]"
                />
                <span className="text-sm font-bold font-mono text-[#16202E]">{minConfidence}</span>
              </div>
            </div>
          </div>
        </div>

        {/* OCR Settings */}
        <div className="rounded-xl border border-[#E1E5EB] bg-white p-6 shadow-2xs">
          <h2 className="mb-4 text-base font-bold font-serif text-[#16202E] flex items-center gap-2 border-b border-slate-50 pb-2">
            OCR Settings
          </h2>
          <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <label className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">OCR Provider</label>
                <select
                  value={ocrProvider}
                  onChange={(e) => updateSingleSetting("ocr.provider", e.target.value)}
                  className="mt-1 block w-full rounded-lg border border-[#E1E5EB] bg-white px-3.5 py-2.5 text-sm text-[#16202E] focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs cursor-pointer font-medium"
                >
                  <option value="google_vision">Google Vision API only</option>
                </select>
                <p className="mt-2 text-xs text-[#5C6B7A] font-semibold leading-relaxed">
                  Scanned pages use Google Vision API. Digital PDF text still uses embedded text and incurs no OCR call.
                </p>
              </div>
              <div>
                <label className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">Google Vision Feature</label>
                <select
                  value={googleFeature}
                  onChange={(e) => updateSingleSetting("google.vision.feature", e.target.value)}
                  disabled={!googleControlsVisible}
                  className="mt-1 block w-full rounded-lg border border-[#E1E5EB] bg-white px-3.5 py-2.5 text-sm text-[#16202E] focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs cursor-pointer font-medium disabled:bg-[#F6F7FA] disabled:text-[#5C6B7A]"
                >
                  <option value="DOCUMENT_TEXT_DETECTION">Document text detection</option>
                  <option value="TEXT_DETECTION">Text detection</option>
                </select>
              </div>
            </div>

            {googleControlsVisible && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6 border-t border-slate-100 pt-4">
                <div>
                  <label className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">Google Vision Auth Mode</label>
                  <select
                    value={googleAuth}
                    onChange={(e) => updateSingleSetting("google.vision.auth", e.target.value)}
                    className="mt-1 block w-full rounded-lg border border-[#E1E5EB] bg-white px-3.5 py-2.5 text-sm text-[#16202E] focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs cursor-pointer font-medium"
                  >
                    <option value="auto">Auto</option>
                    <option value="api_key">API key</option>
                    <option value="adc">Application Default Credentials</option>
                  </select>
                </div>
                <div>
                  <label className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">Google Vision Timeout</label>
                  <input
                    type="number"
                    min="5"
                    max="300"
                    value={googleTimeout}
                    onChange={(e) => updateSingleSetting("google.vision.timeout.seconds", e.target.value)}
                    className="mt-1 block w-full rounded-lg border border-[#E1E5EB] bg-white px-3.5 py-2.5 text-sm font-mono text-[#16202E] focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs font-medium"
                  />
                </div>
                <div className="md:col-span-2">
                  <label className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">Optional language hints</label>
                  <div className="mt-1 flex flex-col gap-2 sm:flex-row">
                    <input
                      type="text"
                      value={googleLanguageHints}
                      onChange={(e) =>
                        setDraftValues((prev) => ({ ...prev, "google.vision.language_hints": e.target.value }))
                      }
                      placeholder="Leave blank for auto-detection, or use en,gu"
                      className="block min-w-0 flex-1 rounded-lg border border-[#E1E5EB] bg-white px-3.5 py-2.5 text-sm text-[#16202E] focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs font-medium"
                    />
                    <button
                      type="button"
                      onClick={() => updateSingleSetting("google.vision.language_hints", googleLanguageHints)}
                      disabled={savingKey === "google.vision.language_hints"}
                      className="rounded-lg border border-[#E1E5EB] bg-white px-4 py-2 text-xs font-semibold text-[#5C6B7A] hover:text-[#16202E] shadow-3xs disabled:cursor-not-allowed disabled:bg-slate-100 cursor-pointer"
                    >
                      Save hints
                    </button>
                  </div>
                  <p className="mt-1.5 text-xs text-[#5C6B7A] font-semibold leading-relaxed">
                    Keep blank for automatic multilingual detection. Add a short BCP-47 list only for noisy regional batches.
                  </p>
                </div>
                <div className="md:col-span-2">
                  <label className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">Google Vision API Key</label>
                  <div className="mt-1 flex flex-col gap-2 sm:flex-row">
                    <input
                      type="password"
                      value={googleApiKeyDraft}
                      onChange={(e) =>
                        setDraftValues((prev) => ({ ...prev, "google.vision.api_key": e.target.value }))
                      }
                      placeholder={
                        googleApiKey?.has_value
                          ? "Saved key configured. Paste a new key to replace it."
                          : "Paste Google Vision API key"
                      }
                      className="block min-w-0 flex-1 rounded-lg border border-[#E1E5EB] bg-white px-3.5 py-2.5 text-sm text-[#16202E] focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs font-medium"
                    />
                    <button
                      type="button"
                      onClick={() => updateSingleSetting("google.vision.api_key", googleApiKeyDraft)}
                      disabled={!googleApiKeyDraft.trim() || savingKey === "google.vision.api_key"}
                      className="rounded-lg bg-[#2B4C7E] hover:bg-[#1E3559] px-4 py-2 text-xs font-semibold text-white shadow-3xs disabled:cursor-not-allowed disabled:bg-slate-300 border-none cursor-pointer"
                    >
                      Save key
                    </button>
                    {googleApiKey?.has_value && (
                      <button
                        type="button"
                        onClick={() => updateSingleSetting("google.vision.api_key", "", { clearSecret: true })}
                        disabled={savingKey === "google.vision.api_key"}
                        className="rounded-lg border border-[#E1E5EB] bg-white px-4 py-2 text-xs font-semibold text-[#5C6B7A] hover:text-[#16202E] shadow-3xs disabled:cursor-not-allowed disabled:bg-slate-100 cursor-pointer"
                      >
                        Clear
                      </button>
                    )}
                  </div>
                  <p className="mt-1.5 text-xs text-[#5C6B7A] font-semibold leading-relaxed">The saved key is hidden after saving and is used only for OCR requests.</p>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* LLM Validation Settings */}
        <div className="rounded-xl border border-[#E1E5EB] bg-white p-6 shadow-2xs">
          <h2 className="mb-4 text-base font-bold font-serif text-[#16202E] flex items-center gap-2 border-b border-slate-50 pb-2">
            🤖 LLM Verification Settings
          </h2>
          <div className="space-y-6">
            <div className="flex items-start justify-between">
              <div>
                <label className="text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] block">
                  Enable LLM Verification checks
                </label>
                <span className="text-xs text-[#5C6B7A] block mt-1 font-semibold leading-relaxed">
                  Toggle dynamic validation checks & checklist evaluations via LLM.
                </span>
              </div>
              <button
                type="button"
                onClick={() => updateSingleSetting("llm_enabled", isLlmEnabled ? "false" : "true")}
                className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                  isLlmEnabled ? "bg-[#2B4C7E]" : "bg-slate-200"
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
                  <label className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">LLM Provider</label>
                  <select
                    value={provider}
                    onChange={(e) => updateSingleSetting("llm_provider", e.target.value)}
                    className="mt-1 block w-full rounded-lg border border-[#E1E5EB] bg-white px-3.5 py-2.5 text-sm text-[#16202E] focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs cursor-pointer font-medium"
                  >
                    <option value="ollama">Ollama (Local)</option>
                    <option value="openai">OpenAI</option>
                    <option value="gemini">Gemini</option>
                  </select>
                </div>
                <div>
                  <label className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">Model Name</label>
                  <input
                    type="text"
                    value={model}
                    onChange={(e) => {}}
                    onBlur={(e) => updateSingleSetting("llm_model", e.target.value)}
                    placeholder="e.g. qwen2.5:7b-instruct-q4_0"
                    className="mt-1 block w-full rounded-lg border border-[#E1E5EB] bg-white px-3.5 py-2.5 text-sm text-[#16202E] focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs font-medium"
                  />
                  <span className="text-[10px] text-[#5C6B7A] font-semibold mt-1 block">Press enter or focus out to save</span>
                </div>
              </div>
            )}
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
      fieldsList = JSON.parse(rawVal);
    } catch (e) {
      // fallback
    }

    let updatedFields: string[];
    if (currentlyRequired) {
      updatedFields = fieldsList.filter((f) => f !== fieldName);
    } else {
      updatedFields = [...fieldsList, fieldName];
    }
    updateSingleSetting(configKey, JSON.stringify(updatedFields));
  };

  const renderFieldsMatrix = () => {
    return (
      <div className="rounded-xl border border-[#E1E5EB] bg-white p-6 shadow-2xs animate-fade-in">
        <h2 className="mb-2 text-base font-bold font-serif text-[#16202E]">📋 Document Verification Fields Matrix</h2>
        <p className="text-xs text-[#5C6B7A] mb-6 font-semibold leading-relaxed">
          Toggle which specific fields are required to pass validation checklist for each document type.
        </p>

        <div className="space-y-6">
          {Object.entries(ALL_FIELD_SCHEMAS).map(([docKey, schema]) => {
            const rawVal = getVal(`required_fields.${docKey}`);
            let enabledFields: string[] = [];
            try {
              enabledFields = JSON.parse(rawVal);
            } catch (e) {
              // fallback
            }

            return (
              <div key={docKey} className="border-b border-[#E1E5EB] pb-5 last:border-0 last:pb-0">
                <h3 className="text-[13.5px] font-bold text-[#16202E] mb-3 font-serif uppercase tracking-wider">{schema.label}</h3>
                <div className="flex flex-wrap gap-3">
                  {schema.fields.map((field) => {
                    const isRequired = enabledFields.includes(field);
                    return (
                      <label
                        key={field}
                        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-semibold cursor-pointer transition-colors ${
                          isRequired
                            ? "bg-[#EAF0F8] border-[#2B4C7E] text-[#2B4C7E]"
                            : "bg-[#F6F7FA] border-[#E1E5EB] text-[#5C6B7A] hover:bg-slate-50"
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={isRequired}
                          onChange={() => handleFieldToggle(docKey, field, isRequired)}
                          className="sr-only"
                        />
                        <span className="font-mono text-[11.5px]">{field}</span>
                        {isRequired && <span className="text-[10px] text-[#2B4C7E]">✓</span>}
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
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold font-serif text-[#16202E]">System settings</h1>
          <p className="text-sm text-[#5C6B7A] mt-1 font-medium">Configure OCR, LLM, and document field verification parameters.</p>
        </div>
        {successMessage && (
          <div className="stamp match select-none rotate-0 py-1.5 px-3">
            {successMessage}
          </div>
        )}
      </div>

      <div className="flex gap-1 border-b border-[#E1E5EB]">
        <button
          type="button"
          onClick={() => setActiveTab("general")}
          className={`pb-3 text-sm font-semibold border-b-2 px-5 transition-colors border-solid -mb-[2px] cursor-pointer ${
            activeTab === "general"
              ? "border-[#2B4C7E] text-[#2B4C7E]"
              : "border-transparent text-[#5C6B7A] hover:text-[#16202E]"
          }`}
        >
          General Configuration
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("fields")}
          className={`pb-3 text-sm font-semibold border-b-2 px-5 transition-colors border-solid -mb-[2px] cursor-pointer ${
            activeTab === "fields"
              ? "border-[#2B4C7E] text-[#2B4C7E]"
              : "border-transparent text-[#5C6B7A] hover:text-[#16202E]"
          }`}
        >
          Required Fields Matrix
        </button>
      </div>

      {loading ? (
        <div className="text-center py-12 text-[#5C6B7A] font-semibold italic">Loading settings...</div>
      ) : activeTab === "general" ? (
        renderGeneralSettings()
      ) : (
        renderFieldsMatrix()
      )}
    </div>
  );
}
