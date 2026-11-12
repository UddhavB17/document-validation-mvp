"use client";

import { useState } from "react";
import dynamic from "next/dynamic";

const ClassificationSettings = dynamic(() => import("@/components/settings/ClassificationSettings").then((module) => module.ClassificationSettings));
const GeneralSettings = dynamic(() => import("@/components/settings/GeneralSettings").then((module) => module.GeneralSettings));
const LlmSettings = dynamic(() => import("@/components/settings/LlmSettings").then((module) => module.LlmSettings));
const OcrSettings = dynamic(() => import("@/components/settings/OcrSettings").then((module) => module.OcrSettings));
const RequiredFieldsMatrix = dynamic(() => import("@/components/settings/RequiredFieldsMatrix").then((module) => module.RequiredFieldsMatrix));
import { SettingsTabs } from "@/components/settings/SettingsTabs";
import { EnvironmentOverrideNotice } from "@/components/settings/EnvironmentOverrideNotice";
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
          <p className="text-sm text-[#5C6B7A] mt-1 font-medium">Configure OCR, LLM, document verification thresholds, and required fields.</p>
        </div>
        {settings.successMessage ? <div className="stamp match select-none rotate-0 py-1.5 px-3">{settings.successMessage}</div> : null}
      </div>
      {settings.errorMessage ? (
        <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
          {settings.errorMessage}
        </div>
      ) : null}

      <SettingsTabs activeTab={activeTab} onChange={setActiveTab} />
      <EnvironmentOverrideNotice settings={settings.settings} />

      {settings.loading ? (
        <div className="text-center py-12 text-[#5C6B7A] font-semibold italic">Loading settings...</div>
      ) : activeTab === "general" ? (
        <GeneralSettings
          getValue={settings.getValue}
          getSetting={settings.getSetting}
          draftValues={settings.draftValues}
          savingKey={settings.savingKey}
          setDraftValue={settings.setDraftValue}
          scheduleSettingUpdate={settings.scheduleSettingUpdate}
          updateSetting={settings.updateSetting}
        />
      ) : activeTab === "classification" ? (
        <ClassificationSettings
          getValue={settings.getValue}
          getSetting={settings.getSetting}
          draftValues={settings.draftValues}
          savingKey={settings.savingKey}
          setDraftValue={settings.setDraftValue}
          scheduleSettingUpdate={settings.scheduleSettingUpdate}
          updateSetting={settings.updateSetting}
        />
      ) : activeTab === "ocr" ? (
        <OcrSettings
          getValue={settings.getValue}
          getSetting={settings.getSetting}
          draftValues={settings.draftValues}
          savingKey={settings.savingKey}
          setDraftValue={settings.setDraftValue}
          updateSetting={settings.updateSetting}
        />
      ) : activeTab === "llm" ? (
        <LlmSettings
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
