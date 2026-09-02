"use client";

import { useCallback, useEffect, useState } from "react";

import { Setting } from "@/components/settings/types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export function useSettings() {
  const [settings, setSettings] = useState<Setting[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [draftValues, setDraftValues] = useState<Record<string, string>>({});

  const fetchSettings = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE_URL}/settings`);
      if (res.ok) {
        const data = (await res.json()) as Setting[];
        setSettings(data);
      }
    } catch (e) {
      console.error("Failed to load settings:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  const showToast = (msg: string) => {
    setSuccessMessage(msg);
    setTimeout(() => setSuccessMessage(null), 3000);
  };

  const getSetting = (key: string) => settings.find((s) => s.config_key === key);
  const getVal = (key: string) => getSetting(key)?.config_value ?? "";

  const updateSingleSetting = async (key: string, newValue: string, options?: { clearSecret?: boolean }) => {
    try {
      setSavingKey(key);
      const res = await fetch(`${API_BASE_URL}/settings/${key}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config_value: newValue, clear_secret: options?.clearSecret ?? false }),
      });
      if (res.ok) {
        const updated = (await res.json()) as Setting;
        setSettings((prev) => prev.map((s) => (s.config_key === key ? { ...s, ...updated } : s)));
        setDraftValues((prev) => ({ ...prev, [key]: "" }));
        showToast("Setting updated successfully!");
      }
    } catch (e) {
      console.error("Failed to update setting:", e);
    } finally {
      setSavingKey(null);
    }
  };

  return {
    settings,
    loading,
    savingKey,
    successMessage,
    draftValues,
    setDraftValues,
    getSetting,
    getVal,
    updateSingleSetting,
  };
}
