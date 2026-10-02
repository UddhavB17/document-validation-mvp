import type { ReactNode } from "react";

type StampTone = "ink" | "ok" | "warn" | "danger" | "electric" | "muted";

const TONE_CLASS: Record<StampTone, string> = {
  ink: "ledger-stamp--ink",
  ok: "ledger-stamp--ok",
  warn: "ledger-stamp--warn",
  danger: "ledger-stamp--danger",
  electric: "ledger-stamp--electric",
  muted: "ledger-stamp--muted",
};

export function LedgerStamp({
  children,
  tone = "muted",
  className = "",
}: {
  children: ReactNode;
  tone?: StampTone;
  className?: string;
}) {
  return <span className={`ledger-stamp ${TONE_CLASS[tone]} ${className}`.trim()}>{children}</span>;
}
