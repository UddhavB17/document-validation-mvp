"use client";

import { useEffect, useRef, useState } from "react";

import { api, Setting } from "@/lib/api";

export function useSettings() {
  const [settings, setSettings] = useState<Setting[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [draftValues, setDraftValues] = useState<Record<string, string>>({});
  const [optimisticValues, setOptimisticValues] = useState<Record<string, string>>({});
  const saveTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    api.settings()
      .then((data) => {
        if (active) setSettings(data);
      })
      .catch((error: unknown) => {
        if (active) console.error("Failed to load settings:", error);
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => () => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    Object.values(saveTimers.current).forEach(clearTimeout);
  }, []);

  function getSetting(key: string) {
    return settings.find((setting) => setting.config_key === key);
  }

  function getValue(key: string): string {
    return optimisticValues[key] ?? getSetting(key)?.config_value ?? "";
  }

  function scheduleSettingUpdate(key: string, value: string) {
    setOptimisticValues((current) => ({ ...current, [key]: value }));
    clearTimeout(saveTimers.current[key]);
    saveTimers.current[key] = setTimeout(() => {
      delete saveTimers.current[key];
      void updateSetting(key, value);
    }, 300);
  }

  function setDraftValue(key: string, value: string) {
    setDraftValues((current) => ({ ...current, [key]: value }));
  }

  async function updateSetting(key: string, value: string, clearSecret = false) {
    try {
      setSavingKey(key);
      const updated = await api.updateSetting(key, value, clearSecret);
      setSettings((current) => current.map((setting) => (
        setting.config_key === key
          ? { ...setting, ...updated, config_value: updated.config_value }
          : setting
      )));
      setOptimisticValues((current) => {
        const next = { ...current };
        delete next[key];
        return next;
      });
      setDraftValues((current) => {
        const next = { ...current };
        delete next[key];
        return next;
      });
      setSuccessMessage("Setting updated successfully!");
      if (toastTimer.current) clearTimeout(toastTimer.current);
      toastTimer.current = setTimeout(() => setSuccessMessage(null), 3000);
    } catch (error: unknown) {
      console.error("Failed to update setting:", error);
    } finally {
      setSavingKey(null);
    }
  }

  return {
    settings,
    loading,
    savingKey,
    successMessage,
    draftValues,
    getSetting,
    getValue,
    setDraftValue,
    scheduleSettingUpdate,
    updateSetting,
  };
}
