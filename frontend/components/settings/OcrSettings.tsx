import { DraftTextField, SecretKeyField, SettingsContext } from "@/components/settings/SettingsControls";

export function OcrSettings({ ctx }: { ctx: SettingsContext }) {
  const { getVal, getSetting, draftValues, setDraftValues, savingKey, updateSingleSetting } = ctx;
  const ocrProvider = getVal("ocr.provider") || "google_vision";
  const googleAuth = getVal("google.vision.auth") || "auto";
  const googleFeature = getVal("google.vision.feature") || "DOCUMENT_TEXT_DETECTION";
  const googleTimeout = getVal("google.vision.timeout.seconds") || "60";
  const googleLanguageHints = draftValues["google.vision.language_hints"] ?? getVal("google.vision.language_hints");
  const googleApiKey = getSetting("google.vision.api_key");
  const googleApiKeyDraft = draftValues["google.vision.api_key"] ?? "";
  const googleControlsVisible = ocrProvider === "google_vision" || ocrProvider === "auto";

  return (
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

        {googleControlsVisible ? (
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
            <DraftTextField
              label="Optional language hints"
              description="Keep blank for automatic multilingual detection. Add a short BCP-47 list only for noisy regional batches."
              placeholder="Leave blank for auto-detection, or use en,gu"
              value={googleLanguageHints}
              isSaving={savingKey === "google.vision.language_hints"}
              onChange={(value) => setDraftValues((prev) => ({ ...prev, "google.vision.language_hints": value }))}
              onSave={() => updateSingleSetting("google.vision.language_hints", googleLanguageHints)}
            />
            <SecretKeyField
              label="Google Vision API Key"
              description="The saved key is hidden after saving and is used only for OCR requests."
              placeholder={
                googleApiKey?.has_value
                  ? "Saved key configured. Paste a new key to replace it."
                  : "Paste Google Vision API key"
              }
              draftValue={googleApiKeyDraft}
              hasSavedValue={Boolean(googleApiKey?.has_value)}
              isSaving={savingKey === "google.vision.api_key"}
              onDraftChange={(value) => setDraftValues((prev) => ({ ...prev, "google.vision.api_key": value }))}
              onSave={() => updateSingleSetting("google.vision.api_key", googleApiKeyDraft)}
              onClear={() => updateSingleSetting("google.vision.api_key", "", { clearSecret: true })}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}
