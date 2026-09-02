import { UploadTab } from "@/lib/types";

function TabButton({ active, children, onClick }: { active: boolean; children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`border-b-2 px-5 py-3 text-sm font-semibold transition-all duration-150 select-none border-solid -mb-[2px] cursor-pointer ${
        active
          ? "border-[#2B4C7E] text-[#2B4C7E] font-bold"
          : "border-transparent text-[#5C6B7A] hover:text-[#16202E]"
      }`}
    >
      {children}
    </button>
  );
}

const TAB_LABELS: { id: UploadTab; label: string }[] = [
  { id: "pdf", label: "PDF Upload" },
  { id: "mapped", label: "Mapped Verification" },
  { id: "json", label: "Partner JSON Intake" },
  { id: "zip", label: "ZIP Package Intake" },
];

export function UploadTabBar({ activeTab, onTabChange }: { activeTab: UploadTab; onTabChange: (tab: UploadTab) => void }) {
  return (
    <div className="flex gap-1 border-b border-[#E1E5EB] mb-2">
      {TAB_LABELS.map((tab) => (
        <TabButton key={tab.id} active={activeTab === tab.id} onClick={() => onTabChange(tab.id)}>
          {tab.label}
        </TabButton>
      ))}
    </div>
  );
}
