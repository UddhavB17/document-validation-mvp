import { SettingsTab } from "./types";

export function SettingsTabs({ activeTab, onChange }: { activeTab: SettingsTab; onChange: (tab: SettingsTab) => void }) {
  return (
    <div className="flex gap-1 border-b border-[#E1E5EB]">
      <button
        type="button"
        onClick={() => onChange("general")}
        className={`pb-3 text-sm font-semibold border-b-2 px-5 transition-colors border-solid -mb-[2px] cursor-pointer ${activeTab === "general" ? "border-[#2B4C7E] text-[#2B4C7E]" : "border-transparent text-[#5C6B7A] hover:text-[#16202E]"}`}
      >
        General Configuration
      </button>
      <button
        type="button"
        onClick={() => onChange("fields")}
        className={`pb-3 text-sm font-semibold border-b-2 px-5 transition-colors border-solid -mb-[2px] cursor-pointer ${activeTab === "fields" ? "border-[#2B4C7E] text-[#2B4C7E]" : "border-transparent text-[#5C6B7A] hover:text-[#16202E]"}`}
      >
        Required Fields Matrix
      </button>
    </div>
  );
}
