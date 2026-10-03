import { UPLOAD_TABS } from "./uploadTabOptions";
import { UploadTab } from "./types";

export { UPLOAD_TABS } from "./uploadTabOptions";

export function UploadTabs({ activeTab, onChange }: { activeTab: UploadTab; onChange: (tab: UploadTab) => void }) {
  return (
    <div className="flex gap-1 border-b border-[#E1E5EB] mb-2" role="tablist" aria-label="Document intake method">
      {UPLOAD_TABS.map((tab) => (
        <button
          key={tab.value}
          id={`upload-tab-${tab.value}`}
          role="tab"
          aria-controls={`upload-panel-${tab.value}`}
          aria-selected={activeTab === tab.value}
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
