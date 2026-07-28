export function PageHeader({ title, description }: { title: string; description?: string }) {
  return (
    <header className="mb-5 border-b border-slate-200 pb-4">
      <h1 className="text-2xl font-semibold text-slate-950">{title}</h1>
      {description ? <p className="mt-1 text-sm text-slate-600">{description}</p> : null}
    </header>
  );
}
