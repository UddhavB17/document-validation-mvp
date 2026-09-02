"use client";

import { SettingsComponentProps } from "./types";

export function OcrSettings({
  getValue,
  getSetting,
  draftValues,
  savingKey,
  setDraftValue,
  updateSetting,
}: SettingsComponentProps) {
  const ocrProvider = getValue("ocr.provider") || "google_vision";
  const googleAuth = getValue("google.vision.auth") || "auto";
  const googleFeature = getValue("google.vision.feature") || "DOCUMENT_TEXT_DETECTION";
  const googleTimeout = getValue("google.vision.timeout.seconds") || "60";
  const googleLanguageHints = draftValues["google.vision.language_hints"] ?? getValue("google.vision.language_hints");
  const googleApiKey = getSetting("google.vision.api_key");
  const googleApiKeyDraft = draftValues["google.vision.api_key"] ?? "";
  const googleControlsVisible = ocrProvider === "google_vision" || ocrProvider === "auto";

  return (
    <div className="rounded-xl border border-[#E1E5EB] bg-white p-6 shadow-2xs">
      <h2 className="mb-4 text-base font-bold font-serif text-[#16202E] flex items-center gap-2 border-b border-slate-50 pb-2">OCR Settings</h2>
      <div className="space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <label className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">OCR Provider</label>
            <select value={ocrProvider} onChange={(event) => updateSetting("ocr.provider", event.target.value)} className="mt-1 block w-full rounded-lg border border-[#E1E5EB] bg-white px-3.5 py-2.5 text-sm text-[#16202E] focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs cursor-pointer font-medium">
              <option value="google_vision">Google Vision API only</option>
            </select>
            <p className="mt-2 text-xs text-[#5C6B7A] font-semibold leading-relaxed">Scanned pages use Google Vision API. Digital PDF text still uses embedded text and incurs no OCR call.</p>
          </div>
          <div>
            <label className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">Google Vision Feature</label>
            <select value={googleFeature} onChange={(event) => updateSetting("google.vision.feature", event.target.value)} disabled={!googleControlsVisible} className="mt-1 block w-full rounded-lg border border-[#E1E5EB] bg-white px-3.5 py-2.5 text-sm text-[#16202E] focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs cursor-pointer font-medium disabled:bg-[#F6F7FA] disabled:text-[#5C6B7A]">
              <option value="DOCUMENT_TEXT_DETECTION">Document text detection</option>
              <option value="TEXT_DETECTION">Text detection</option>
            </select>
          </div>
        </div>

        {googleControlsVisible ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 border-t border-slate-100 pt-4">
            <div>
              <label className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">Google Vision Auth Mode</label>
              <select value={googleAuth} onChange={(event) => updateSetting("google.vision.auth", event.target.value)} className="mt-1 block w-full rounded-lg border border-[#E1E5EB] bg-white px-3.5 py-2.5 text-sm text-[#16202E] focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs cursor-pointer font-medium">
                <option value="auto">Auto</option>
                <option value="api_key">API key</option>
                <option value="adc">Application Default Credentials</option>
              </select>
            </div>
            <div>
              <label className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">Google Vision Timeout</label>
              <input type="number" min="5" max="300" value={googleTimeout} onChange={(event) => updateSetting("google.vision.timeout.seconds", event.target.value)} className="mt-1 block w-full rounded-lg border border-[#E1E5EB] bg-white px-3.5 py-2.5 text-sm font-mono text-[#16202E] focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs font-medium" />
            </div>
            <DraftTextField
              label="Optional language hints"
              description="Keep blank for automatic multilingual detection. Add a short BCP-47 list only for noisy regional batches."
              placeholder="Leave blank for auto-detection, or use en,gu"
              value={googleLanguageHints}
              isSaving={savingKey === "google.vision.language_hints"}
              onChange={(value) => setDraftValue("google.vision.language_hints", value)}
              onSave={() => updateSetting("google.vision.language_hints", googleLanguageHints)}
            />
            <SecretKeyField
              label="Google Vision API Key"
              description="The saved key is hidden after saving and is used only for OCR requests."
              placeholder={googleApiKey?.has_value ? "Saved key configured. Paste a new key to replace it." : "Paste Google Vision API key"}
              draftValue={googleApiKeyDraft}
              hasSavedValue={Boolean(googleApiKey?.has_value)}
              isSaving={savingKey === "google.vision.api_key"}
              onDraftChange={(value) => setDraftValue("google.vision.api_key", value)}
              onSave={() => updateSetting("google.vision.api_key", googleApiKeyDraft)}
              onClear={() => updateSetting("google.vision.api_key", "", true)}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}

function DraftTextField({
  label,
  description,
  placeholder,
  value,
  isSaving,
  onChange,
  onSave,
}: {
  label: string;
  description: string;
  placeholder: string;
  value: string;
  isSaving: boolean;
  onChange: (value: string) => void;
  onSave: () => void;
}) {
  return (
    <div className="md:col-span-2">
      <label className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">{label}</label>
      <div className="mt-1 flex flex-col gap-2 sm:flex-row">
        <input type="text" value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="block min-w-0 flex-1 rounded-lg border border-[#E1E5EB] bg-white px-3.5 py-2.5 text-sm text-[#16202E] focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs font-medium" />
        <button type="button" onClick={onSave} disabled={isSaving} className="rounded-lg border border-[#E1E5EB] bg-white px-4 py-2 text-xs font-semibold text-[#5C6B7A] hover:text-[#16202E] shadow-3xs disabled:cursor-not-allowed disabled:bg-slate-100 cursor-pointer">Save hints</button>
      </div>
      <p className="mt-1.5 text-xs text-[#5C6B7A] font-semibold leading-relaxed">{description}</p>
    </div>
  );
}

function SecretKeyField({
  label,
  description,
  placeholder,
  draftValue,
  hasSavedValue,
  isSaving,
  onDraftChange,
  onSave,
  onClear,
}: {
  label: string;
  description: string;
  placeholder: string;
  draftValue: string;
  hasSavedValue: boolean;
  isSaving: boolean;
  onDraftChange: (value: string) => void;
  onSave: () => void;
  onClear: () => void;
}) {
  return (
    <div className="md:col-span-2">
      <label className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">{label}</label>
      <div className="mt-1 flex flex-col gap-2 sm:flex-row">
        <input type="password" value={draftValue} onChange={(event) => onDraftChange(event.target.value)} placeholder={placeholder} className="block min-w-0 flex-1 rounded-lg border border-[#E1E5EB] bg-white px-3.5 py-2.5 text-sm text-[#16202E] focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs font-medium" />
        <button type="button" onClick={onSave} disabled={!draftValue.trim() || isSaving} className="rounded-lg bg-[#2B4C7E] hover:bg-[#1E3559] px-4 py-2 text-xs font-semibold text-white shadow-3xs disabled:cursor-not-allowed disabled:bg-slate-300 border-none cursor-pointer">Save key</button>
        {hasSavedValue ? <button type="button" onClick={onClear} disabled={isSaving} className="rounded-lg border border-[#E1E5EB] bg-white px-4 py-2 text-xs font-semibold text-[#5C6B7A] hover:text-[#16202E] shadow-3xs disabled:cursor-not-allowed disabled:bg-slate-100 cursor-pointer">Clear</button> : null}
      </div>
      <p className="mt-1.5 text-xs text-[#5C6B7A] font-semibold leading-relaxed">{description}</p>
    </div>
  );
}
