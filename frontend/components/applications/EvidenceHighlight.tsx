export function HighlightedEvidenceText({ text, needle }: { text: string; needle: string }) {
  const cleanedNeedle = needle.trim();
  if (cleanedNeedle.length < 4) {
    return <>{text}</>;
  }
  const index = text.toLowerCase().indexOf(cleanedNeedle.toLowerCase());
  if (index < 0) {
    return <>{text}</>;
  }
  return (
    <>
      {text.slice(0, index)}
      <mark className="rounded bg-amber-300 px-0.5 text-slate-950">{text.slice(index, index + cleanedNeedle.length)}</mark>
      {text.slice(index + cleanedNeedle.length)}
    </>
  );
}
