import { UPLOAD_TABS } from "./uploadTabOptions";
import { UploadTab } from "./types";

export { UPLOAD_TABS } from "./uploadTabOptions";

export function UploadTabs({ activeTab, onChange, disabled = false }: { activeTab: UploadTab; onChange: (tab: UploadTab) => void; disabled?: boolean }) {
  return (
    <div className="mb-2 flex flex-wrap gap-1 border-b border-[#E1E5EB]" role="tablist" aria-label="Document intake method">
      {UPLOAD_TABS.map((tab) => (
        <button
          key={tab.value}
          id={`upload-tab-${tab.value}`}
          role="tab"
          aria-controls={`upload-panel-${tab.value}`}
          aria-selected={activeTab === tab.value}
          tabIndex={activeTab === tab.value ? 0 : -1}
          disabled={disabled}
          type="button"
          onClick={() => onChange(tab.value)}
          onKeyDown={(event) => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key) || disabled) return;
            event.preventDefault();
            const index = UPLOAD_TABS.findIndex((item) => item.value === tab.value);
            const nextIndex = event.key === "Home" ? 0 : event.key === "End" ? UPLOAD_TABS.length - 1 :
              (index + (event.key === "ArrowRight" ? 1 : -1) + UPLOAD_TABS.length) % UPLOAD_TABS.length;
            onChange(UPLOAD_TABS[nextIndex].value);
            const next = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("[role=tab]")[nextIndex];
            next?.focus();
          }}
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
