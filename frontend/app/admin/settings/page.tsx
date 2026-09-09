"use client";

import { useState } from "react";

import { GeneralSettings } from "@/components/settings/GeneralSettings";
import { RequiredFieldsMatrix } from "@/components/settings/RequiredFieldsMatrix";
import { SettingsTabs } from "@/components/settings/SettingsTabs";
import { useSettings } from "@/components/settings/useSettings";
import { SettingsTab } from "@/components/settings/types";

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<SettingsTab>("general");
  const settings = useSettings();

  return (
    <div className="max-w-4xl mx-auto space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold font-serif text-[#16202E]">System settings</h1>
          <p className="text-sm text-[#5C6B7A] mt-1 font-medium">Configure OCR, LLM, and document field verification parameters.</p>
        </div>
        {settings.successMessage ? <div className="stamp match select-none rotate-0 py-1.5 px-3">{settings.successMessage}</div> : null}
      </div>

      <SettingsTabs activeTab={activeTab} onChange={setActiveTab} />

      {settings.loading ? (
        <div className="text-center py-12 text-[#5C6B7A] font-semibold italic">Loading settings...</div>
      ) : activeTab === "general" ? (
        <GeneralSettings
          getValue={settings.getValue}
          getSetting={settings.getSetting}
          draftValues={settings.draftValues}
          savingKey={settings.savingKey}
          setDraftValue={settings.setDraftValue}
          updateSetting={settings.updateSetting}
        />
      ) : (
        <RequiredFieldsMatrix getValue={settings.getValue} updateSetting={settings.updateSetting} />
      )}
    </div>
  );
}
