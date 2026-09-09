"use client";

import { ClassificationSettings } from "./ClassificationSettings";
import { LlmSettings } from "./LlmSettings";
import { OcrSettings } from "./OcrSettings";
import { SettingsComponentProps } from "./types";

export function GeneralSettings(props: SettingsComponentProps) {
  return (
    <div className="space-y-8 animate-fade-in">
      <ClassificationSettings {...props} />
      <OcrSettings {...props} />
      <LlmSettings {...props} />
    </div>
  );
}
