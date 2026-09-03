import type { Setting } from "@/lib/api";

export type SettingsTab = "general" | "fields";

export interface DocumentFieldSchema {
  label: string;
  fields: readonly string[];
}

export interface SettingsComponentProps {
  getValue: (key: string) => string;
  getSetting: (key: string) => Setting | undefined;
  draftValues: Record<string, string>;
  savingKey: string | null;
  setDraftValue: (key: string, value: string) => void;
  updateSetting: (key: string, value: string, clearSecret?: boolean) => Promise<void>;
}
