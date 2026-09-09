import Link from "next/link";

type CaseLoadingSkeletonProps = {
  message?: string;
};

export function CaseLoadingSkeleton({ message = "Loading application review..." }: CaseLoadingSkeletonProps) {
  return (
    <div className="w-full min-w-0 space-y-4" role="status" aria-label={message}>
      <div className="h-5 w-28 animate-pulse rounded bg-slate-200" />
      <div className="rounded-xl border border-[#E1E5EB] bg-white p-5 shadow-2xs">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-3">
            <div className="h-5 w-64 animate-pulse rounded bg-slate-200" />
            <div className="h-3 w-80 max-w-full animate-pulse rounded bg-slate-100" />
          </div>
          <div className="h-7 w-24 animate-pulse rounded-full bg-slate-100" />
        </div>
        <div className="mt-5 grid grid-cols-2 gap-3 border-t border-slate-100 pt-4 sm:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="space-y-2">
              <div className="h-2.5 w-16 animate-pulse rounded bg-slate-100" />
              <div className="h-4 w-24 animate-pulse rounded bg-slate-200" />
            </div>
          ))}
        </div>
      </div>
      <div className="h-11 animate-pulse rounded-xl border border-slate-100 bg-white" />
      <div className="space-y-3 rounded-xl border border-[#E1E5EB] bg-white p-5">
        <div className="h-4 w-36 animate-pulse rounded bg-slate-200" />
        <div className="h-3 w-full animate-pulse rounded bg-slate-100" />
        <div className="h-3 w-4/5 animate-pulse rounded bg-slate-100" />
        <div className="h-24 animate-pulse rounded-lg bg-slate-50" />
      </div>
      <p className="sr-only">{message}</p>
    </div>
  );
}

type CaseErrorStateProps = {
  title: string;
  message: string;
  onRetry?: () => void;
};

export function CaseErrorState({ title, message, onRetry }: CaseErrorStateProps) {
  return (
    <section className="w-full min-w-0 rounded-xl border border-red-200 bg-red-50 p-5 text-red-900" role="alert">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-base font-bold">{title}</h1>
          <p className="mt-1 max-w-2xl text-sm leading-relaxed text-red-800">{message}</p>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/admin/worklist" className="rounded-lg border border-red-300 bg-white px-3.5 py-2 text-sm font-bold text-red-800 shadow-3xs transition-colors hover:bg-red-100">
            Back to Worklist
          </Link>
          {onRetry ? (
            <button
              type="button"
              onClick={onRetry}
              className="rounded-lg border border-red-300 bg-white px-3.5 py-2 text-sm font-bold text-red-800 shadow-3xs transition-colors hover:bg-red-100"
            >
              Retry
            </button>
          ) : null}
        </div>
      </div>
    </section>
  );
}
