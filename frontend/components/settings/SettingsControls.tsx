import { Setting } from "@/components/settings/types";

export function SecretKeyField({
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
  onClear?: () => void;
}) {
  return (
    <div className="md:col-span-2">
      <label className="block text-[11px] font-bold uppercase tracking-wider text-[#5C6B7A] mb-2">{label}</label>
      <div className="mt-1 flex flex-col gap-2 sm:flex-row">
        <input
          type="password"
          value={draftValue}
          onChange={(e) => onDraftChange(e.target.value)}
          placeholder={placeholder}
          className="block min-w-0 flex-1 rounded-lg border border-[#E1E5EB] bg-white px-3.5 py-2.5 text-sm text-[#16202E] focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs font-medium"
        />
        <button
          type="button"
          onClick={onSave}
          disabled={!draftValue.trim() || isSaving}
          className="rounded-lg bg-[#2B4C7E] hover:bg-[#1E3559] px-4 py-2 text-xs font-semibold text-white shadow-3xs disabled:cursor-not-allowed disabled:bg-slate-300 border-none cursor-pointer"
        >
          Save key
        </button>
        {hasSavedValue && onClear ? (
          <button
            type="button"
            onClick={onClear}
            disabled={isSaving}
            className="rounded-lg border border-[#E1E5EB] bg-white px-4 py-2 text-xs font-semibold text-[#5C6B7A] hover:text-[#16202E] shadow-3xs disabled:cursor-not-allowed disabled:bg-slate-100 cursor-pointer"
          >
            Clear
          </button>
        ) : null}
      </div>
      <p className="mt-1.5 text-xs text-[#5C6B7A] font-semibold leading-relaxed">{description}</p>
    </div>
  );
}

export function DraftTextField({
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
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="block min-w-0 flex-1 rounded-lg border border-[#E1E5EB] bg-white px-3.5 py-2.5 text-sm text-[#16202E] focus:border-[#2B4C7E] focus:outline-none focus:ring-1 focus:ring-[#2B4C7E]/10 shadow-3xs font-medium"
        />
        <button
          type="button"
          onClick={onSave}
          disabled={isSaving}
          className="rounded-lg border border-[#E1E5EB] bg-white px-4 py-2 text-xs font-semibold text-[#5C6B7A] hover:text-[#16202E] shadow-3xs disabled:cursor-not-allowed disabled:bg-slate-100 cursor-pointer"
        >
          Save hints
        </button>
      </div>
      <p className="mt-1.5 text-xs text-[#5C6B7A] font-semibold leading-relaxed">{description}</p>
    </div>
  );
}

export type SettingsContext = {
  getVal: (key: string) => string;
  getSetting: (key: string) => Setting | undefined;
  draftValues: Record<string, string>;
  setDraftValues: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  savingKey: string | null;
  updateSingleSetting: (key: string, newValue: string, options?: { clearSecret?: boolean }) => Promise<void>;
};
