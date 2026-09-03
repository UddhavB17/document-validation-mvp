import type { ReactNode } from "react";

export function HighlightedEvidenceText({ text, needle }: { text: string; needle: string }) {
  const cleanedNeedle = needle.trim().slice(0, 160);
  if (cleanedNeedle.length < 4) {
    return <>{text}</>;
  }

  const lowerText = text.toLowerCase();
  const lowerNeedle = cleanedNeedle.toLowerCase();
  const parts: ReactNode[] = [];
  let cursor = 0;
  let matchIndex = lowerText.indexOf(lowerNeedle, cursor);
  let matchNumber = 0;

  while (matchIndex >= 0) {
    if (matchIndex > cursor) {
      parts.push(text.slice(cursor, matchIndex));
    }
    parts.push(
      <mark key={`evidence-match-${matchNumber}`} className="rounded bg-amber-300 px-0.5 text-slate-950">
        {text.slice(matchIndex, matchIndex + cleanedNeedle.length)}
      </mark>,
    );
    matchNumber += 1;
    cursor = matchIndex + cleanedNeedle.length;
    matchIndex = lowerText.indexOf(lowerNeedle, cursor);
  }

  if (matchNumber === 0) return <>{text}</>;
  if (cursor < text.length) parts.push(text.slice(cursor));
  return <>{parts}</>;
}
