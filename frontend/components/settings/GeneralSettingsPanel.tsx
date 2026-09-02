import { ClassificationSettings } from "@/components/settings/ClassificationSettings";
import { LlmSettings } from "@/components/settings/LlmSettings";
import { OcrSettings } from "@/components/settings/OcrSettings";
import { SettingsContext } from "@/components/settings/SettingsControls";

export function GeneralSettingsPanel({ ctx }: { ctx: SettingsContext }) {
  const { getVal, updateSingleSetting } = ctx;
  const minConfidence = parseFloat(getVal("min_confidence") || "0.70");

  return (
    <div className="space-y-8 animate-fade-in">
      <ClassificationSettings
        minConfidence={minConfidence}
        onConfidenceChange={(value) => updateSingleSetting("min_confidence", value)}
      />
      <OcrSettings ctx={ctx} />
      <LlmSettings ctx={ctx} />
    </div>
  );
}
