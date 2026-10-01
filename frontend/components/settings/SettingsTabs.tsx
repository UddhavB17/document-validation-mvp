import { SettingsTab } from "./types";

export function SettingsTabs({ activeTab, onChange }: { activeTab: SettingsTab; onChange: (tab: SettingsTab) => void }) {
  const tabs: { id: SettingsTab; label: string }[] = [
    { id: "general", label: "Overview" },
    { id: "classification", label: "Classification & Thresholds" },
    { id: "fields", label: "Required Fields Matrix" },
    { id: "ocr", label: "OCR Provider" },
    { id: "llm", label: "LLM Verification" },
  ];

  return (
    <div className="flex gap-1 border-b border-[#E1E5EB] overflow-x-auto pb-px">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          onClick={() => onChange(tab.id)}
          className={`pb-3 text-xs md:text-sm font-semibold border-b-2 px-4 whitespace-nowrap transition-colors border-solid -mb-[2px] cursor-pointer ${
            activeTab === tab.id
              ? "border-[#2B4C7E] text-[#2B4C7E]"
              : "border-transparent text-[#5C6B7A] hover:text-[#16202E]"
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
