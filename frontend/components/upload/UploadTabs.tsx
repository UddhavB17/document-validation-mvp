import { UploadTab } from "./types";

const tabs: Array<{ value: UploadTab; label: string }> = [
  { value: "pdf", label: "PDF Upload" },
  { value: "mapped", label: "Mapped Verification" },
  { value: "json", label: "Partner JSON Intake" },
  { value: "zip", label: "ZIP Package Intake" },
];

export function UploadTabs({ activeTab, onChange }: { activeTab: UploadTab; onChange: (tab: UploadTab) => void }) {
  return (
    <div className="flex gap-1 border-b border-[#E1E5EB] mb-2">
      {tabs.map((tab) => (
        <button
          key={tab.value}
          type="button"
          onClick={() => onChange(tab.value)}
          className={`border-b-2 px-5 py-3 text-sm font-semibold transition-all duration-150 select-none border-solid -mb-[2px] cursor-pointer ${
            activeTab === tab.value
              ? "border-[#2B4C7E] text-[#2B4C7E] font-bold"
              : "border-transparent text-[#5C6B7A] hover:text-[#16202E]"
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
