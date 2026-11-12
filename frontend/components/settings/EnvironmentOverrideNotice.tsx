import type { Setting } from "@/lib/api";

export function EnvironmentOverrideNotice({ settings }: { settings: Setting[] }) {
  const overridden = settings.filter((setting) => setting.env_override_active);
  if (overridden.length === 0) return null;

  return (
    <aside className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950" role="status">
      <p className="font-semibold">Some saved values are overridden by the runtime environment.</p>
      <ul className="mt-2 space-y-1">
        {overridden.map((setting) => (
          <li key={setting.config_key}>
            <span className="font-medium">{setting.label || setting.config_key}:</span>{" "}
            active value <code>{setting.effective_value ?? "unavailable"}</code>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs">Changing the saved value will not change runtime behavior until the environment override is removed.</p>
    </aside>
  );
}
