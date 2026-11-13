"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { ErrorMessage, LoadingMessage } from "@/components/Message";
const EvidenceWizard = dynamic(
  () => import("@/components/ops/EvidenceWizard").then((module) => module.EvidenceWizard),
  { ssr: false },
);
import type { WizardMode } from "@/components/ops/EvidenceWizard";
import { FindingsList, PagesToVerifyChips } from "@/components/ops/FindingsList";
import { LedgerStamp } from "@/components/ops/LedgerStamp";
import { OpsChecklist } from "@/components/ops/OpsChecklist";
import { clampPercentage, opsFindingExplanation, pickText, statusProgressPercentage, takeTopFindings } from "@/components/ops/opsUtils";
import { normalizeOpsStatus } from "@/components/ops/StatusPill";
import type { OpsFinding } from "@/lib/api";
import { t, useLocale } from "@/lib/i18n";
import { isApplicationReviewPollingStatus, useApplicationStatus, useClaimOpsCase, useCurrentUser, useOpsApplication, useOpsWorkflow, useReleaseOpsCase, useRequestOpsDocuments, useReviewNextOpsCase, useSaveOpsCheck, useUpdateOpsDocumentItem } from "@/lib/queries";

function OpsWorkflowPanel({ applicationId, onOpenPage }: { applicationId: number; onOpenPage: (page: number) => void }) {
  const { locale } = useLocale();
  const workflow = useOpsWorkflow(applicationId);
  const currentUser = useCurrentUser();
  const claimCase = useClaimOpsCase(applicationId);
  const releaseCase = useReleaseOpsCase(applicationId);
  const saveCheck = useSaveOpsCheck(applicationId);
  const requestDocuments = useRequestOpsDocuments(applicationId);
  const updateDocument = useUpdateOpsDocumentItem(applicationId);
  const nextCase = useReviewNextOpsCase();
  const [requestedItems, setRequestedItems] = useState("");
  const [requestMessage, setRequestMessage] = useState("");
  const [followUpAt, setFollowUpAt] = useState("");
  const [linkedFileId, setLinkedFileId] = useState("");
  const [feedback, setFeedback] = useState("");
  const data = workflow.data;
  const ownerId = data?.case.owner_user_id;
  const isOwner = ownerId === currentUser.data?.id;
  const titleFor = (value: unknown) => {
    if (typeof value === "string") return value;
    if (value && typeof value === "object") {
      const localized = value as { en?: unknown; hi?: unknown };
      const selected = localized[locale] ?? localized.en;
      return typeof selected === "string" ? selected : "Review item";
    }
    return "Review item";
  };
  async function sendDocumentRequest() {
    const items = requestedItems.split("\n").map((item) => item.trim()).filter(Boolean);
    try {
      await requestDocuments.mutateAsync({ message: requestMessage, items, follow_up_at: followUpAt ? new Date(followUpAt).toISOString() : undefined });
      setRequestedItems(""); setRequestMessage(""); setFeedback("Document request saved. This case is now waiting for documents.");
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : "Could not save the document request.");
    }
  }

  if (workflow.isLoading) return <div className="ledger-surface p-4 text-sm text-desk-muted">Loading Ops workflow…</div>;
  if (workflow.isError || !data) return <div className="ledger-surface p-4 text-sm text-desk-muted">Could not load Ops ownership and follow-up. <button type="button" className="ledger-link" onClick={() => void workflow.refetch()}>Retry</button></div>;
  return (
    <section className="ledger-surface space-y-5 p-4 sm:p-5" aria-label="Ops workflow">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-xl font-semibold text-desk-ink">Case ownership and progress</h2>
          <p className="mt-1 text-xs text-desk-muted">{data.case.owner_name ? `Owned by ${data.case.owner_name}` : "No reviewer owns this case"} · Ready since {data.case.ready_at ? new Date(data.case.ready_at).toLocaleString() : "time unknown"}</p>
          {data.case.waiting_reason ? <p className="mt-1 text-xs font-semibold text-desk-muted">{data.case.waiting_reason}</p> : null}
        </div>
        {isOwner ? (
          <button type="button" className="ledger-btn ledger-btn--outline" onClick={() => void releaseCase.mutateAsync(undefined).catch((error) => setFeedback(error instanceof Error ? error.message : "Could not release this case."))}>Release case</button>
        ) : ownerId === null ? (
          <button type="button" className="ledger-btn ledger-btn--electric" onClick={() => void claimCase.mutateAsync(undefined).catch((error) => setFeedback(error instanceof Error ? error.message : "Could not claim this case."))}>Claim case</button>
        ) : null}
      </div>

      <div>
        <h3 className="text-sm font-bold text-desk-ink">Saved review checks</h3>
        {data.changed_review_items > 0 ? <p role="status" className="mt-2 rounded-desk border border-amber-300 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-900">{data.changed_review_items} saved check(s) no longer match the current evidence or checklist. Recheck them before recording an outcome.</p> : null}
        <ul className="mt-2 divide-y divide-[color:var(--border)]">
          {data.review_items.map((item) => (
            <li key={item.check_key} className="flex flex-wrap items-center justify-between gap-3 py-3">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-desk-ink">{titleFor(item.title)}</p>
                {item.pages.length ? <button type="button" className="ledger-link text-xs" onClick={() => onOpenPage(item.pages[0])}>Open source page {item.pages[0]} →</button> : null}
                {item.note ? <p className="text-xs text-desk-muted">{item.note}</p> : null}
                {item.status ? <p className="text-xs font-semibold text-desk-indigo">Saved: {item.status}</p> : null}
              </div>
              {isOwner ? (
                <div className="flex flex-wrap gap-2">
                  {(["checked", "exception_confirmed", "needs_help"] as const).map((status) => (
                    <button key={status} type="button" className={`ledger-filter-chip${item.status === status ? " is-active" : ""}`} disabled={saveCheck.isPending} onClick={() => void saveCheck.mutateAsync({ check_key: item.check_key, evidence_revision: item.evidence_revision, status }).catch((error) => setFeedback(error instanceof Error ? error.message : "Could not save this check."))}>{status === "checked" ? "Checked" : status === "exception_confirmed" ? "Exception confirmed" : "Needs help"}</button>
                  ))}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-2">
          <h3 className="text-sm font-bold text-desk-ink">Request documents</h3>
          <label className="block text-xs font-semibold text-desk-muted">Items, one per line<textarea className="ledger-input mt-1 min-h-20 w-full" value={requestedItems} onChange={(event) => setRequestedItems(event.target.value)} /></label>
          <label className="block text-xs font-semibold text-desk-muted">Message<textarea className="ledger-input mt-1 min-h-20 w-full" value={requestMessage} onChange={(event) => setRequestMessage(event.target.value)} /></label>
          <label className="block text-xs font-semibold text-desk-muted">Follow-up date<input className="ledger-input mt-1 w-full" type="date" value={followUpAt} onChange={(event) => setFollowUpAt(event.target.value)} /></label>
          <button type="button" className="ledger-btn ledger-btn--electric" disabled={!isOwner || requestDocuments.isPending} onClick={() => void sendDocumentRequest()}>{requestDocuments.isPending ? "Saving…" : "Save request and wait"}</button>
        </div>
        <div>
          <h3 className="text-sm font-bold text-desk-ink">Document follow-up</h3>
          {data.document_requests.length === 0 ? <p className="mt-2 text-sm text-desk-faint">No document requests recorded.</p> : null}
          {data.document_requests.map((request) => (
            <div key={request.id} className="mt-2 rounded-desk border border-[color:var(--border)] p-3">
              <p className="text-sm font-semibold text-desk-ink">{request.status === "open" ? "Waiting for documents" : "Request resolved"}</p>
              <p className="mt-1 whitespace-pre-wrap text-xs text-desk-muted">{request.message}</p>
              {request.follow_up_at ? <p className="mt-1 text-xs text-desk-muted">Follow up: {new Date(request.follow_up_at).toLocaleDateString()}</p> : null}
              {data.document_request_items.filter((item) => item.request_id === request.id).map((item) => (
                <div key={item.id} className="mt-2 flex flex-wrap items-center justify-between gap-2 border-t border-[color:var(--border)] pt-2 text-xs">
                  <span>{item.item} · {item.status}{item.uploaded_file_id ? ` · file ${item.uploaded_file_id}` : ""}</span>
                  {request.status === "open" && isOwner ? <div className="flex gap-2"><input aria-label="Uploaded file ID" className="ledger-input !min-h-8 w-24" type="number" min="1" value={linkedFileId} onChange={(event) => setLinkedFileId(event.target.value)} placeholder="File ID" /><button type="button" className="ledger-link" onClick={() => void updateDocument.mutateAsync({ requestId: request.id, itemId: item.id, status: "received", uploadedFileId: linkedFileId ? Number(linkedFileId) : undefined }).catch((error) => setFeedback(error instanceof Error ? error.message : "Could not update this item."))}>Received</button><button type="button" className="ledger-link" onClick={() => void updateDocument.mutateAsync({ requestId: request.id, itemId: item.id, status: "outstanding" }).catch((error) => setFeedback(error instanceof Error ? error.message : "Could not update this item."))}>Still outstanding</button></div> : null}
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>

      <div>
        <h3 className="text-sm font-bold text-desk-ink">Case history</h3>
        <ul className="mt-2 space-y-1 text-xs text-desk-muted">{data.events.slice(0, 8).map((event) => <li key={event.id}>{event.actor_name || "System"} · {event.action.replace(/_/g, " ")} · {new Date(event.occurred_at).toLocaleString()}{event.reason ? ` · ${event.reason}` : ""}</li>)}</ul>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" className="ledger-btn ledger-btn--outline" disabled={nextCase.isPending} onClick={() => void nextCase.mutateAsync(undefined).then((result) => { const nextId = (result as { application_id?: number | null }).application_id; if (nextId) window.location.assign(`/ops/applications/${nextId}`); else setFeedback("No other ready case is available."); })}>Review next</button>
        {data.latest_decision ? <p className="text-sm font-semibold text-desk-muted">Latest outcome: {data.latest_decision.decision} · {data.latest_decision.decided_at ? new Date(data.latest_decision.decided_at).toLocaleString() : "time unknown"}</p> : null}
        {feedback ? <p role="status" className="text-sm text-desk-muted">{feedback}</p> : null}
      </div>
    </section>
  );
}

export default function OpsApplicationPage() {
  const params = useParams<{ id: string }>();
  const applicationId = Number(params.id);
  const isValid = Number.isInteger(applicationId) && applicationId > 0;
  const { locale } = useLocale();
  const ops = useOpsApplication(isValid ? applicationId : null);
  const status = useApplicationStatus(isValid ? applicationId : null);
  const [wizard, setWizard] = useState<WizardMode | null>(null);
  const [resolvedCodes, setResolvedCodes] = useState<Set<string>>(() => new Set());
  const wasProcessing = useRef(false);

  const liveStatus = status.data?.status ?? ops.data?.status;
  const processing = normalizeOpsStatus(liveStatus) === "processing";

  useEffect(() => {
    if (processing) {
      wasProcessing.current = true;
    }
  }, [processing]);

  useEffect(() => {
    if (wasProcessing.current && liveStatus && !isApplicationReviewPollingStatus(liveStatus)) {
      wasProcessing.current = false;
      void ops.refetch();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveStatus]);

  useEffect(() => {
    setResolvedCodes(new Set());
    setWizard(null);
  }, [applicationId]);

  const findings = useMemo(() => takeTopFindings(ops.data?.top_findings ?? []), [ops.data?.top_findings]);
  const openFindings = useMemo(
    () => findings.filter((finding) => !resolvedCodes.has(finding.code)),
    [findings, resolvedCodes],
  );
  const activeFinding = openFindings[0] ?? null;

  const openWizardForFinding = (finding: OpsFinding) => {
    const index = openFindings.findIndex((item) => item.code === finding.code);
    setWizard({ kind: "finding", index: Math.max(0, index) });
  };

  const markOk = (finding: OpsFinding) => {
    setResolvedCodes((current) => {
      const next = new Set(current);
      next.add(finding.code);
      return next;
    });
    setWizard((current) => {
      if (!current || current.kind !== "finding") {
        return current;
      }
      const remaining = openFindings.filter((item) => item.code !== finding.code);
      if (remaining.length === 0) {
        return null;
      }
      const nextIndex = Math.min(current.index, remaining.length - 1);
      return { kind: "finding", index: nextIndex };
    });
  };

  if (!isValid) {
    return (
      <div className="mx-auto max-w-[1100px] space-y-4">
        <ErrorMessage message={t(locale, "ops.review.loadError")} />
        <Link href="/ops" className="ledger-link text-sm">
          {t(locale, "ops.review.back")}
        </Link>
      </div>
    );
  }

  if (ops.isLoading) {
    return (
      <div className="mx-auto max-w-[1180px] space-y-4">
        <div className="h-16 rounded-desk ledger-shimmer" />
        <div className="h-28 rounded-desk ledger-shimmer" />
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(280px,.8fr)]">
          <div className="h-80 rounded-desk ledger-shimmer" />
          <div className="h-80 rounded-desk ledger-shimmer" />
        </div>
        <LoadingMessage message={t(locale, "ops.review.loading")} />
      </div>
    );
  }

  if (ops.isError || !ops.data) {
    return (
      <div className="mx-auto max-w-[1100px] space-y-4">
        <ErrorMessage message={t(locale, "ops.review.loadError")} />
        <div className="flex gap-3">
          <button type="button" onClick={() => void ops.refetch()} className="ledger-btn ledger-btn--outline">
            {t(locale, "ops.common.retry")}
          </button>
          <Link href="/ops" className="ledger-btn ledger-btn--electric">
            {t(locale, "ops.review.back")}
          </Link>
        </div>
      </div>
    );
  }

  const data = ops.data;
  const opsStatus = normalizeOpsStatus(liveStatus);
  const statusPercentage = statusProgressPercentage(status.data);
  const percentage = statusPercentage ?? clampPercentage(data.processing.percentage);
  const failureReason = status.data?.job?.failure_reason ?? data.processing.failure_reason;

  if (wizard) {
    return (
      <EvidenceWizard
        application={data}
        findings={findings}
        mode={wizard}
        resolvedCodes={resolvedCodes}
        onClose={() => setWizard(null)}
        onMarkOk={markOk}
        onFlag={() => {
          if (wizard.kind === "finding") {
            const remaining = openFindings;
            if (wizard.index < remaining.length - 1) {
              setWizard({ kind: "finding", index: wizard.index + 1 });
            }
          }
        }}
        onChangeIndex={(index) => setWizard({ kind: "finding", index })}
      />
    );
  }

  return (
    <div className="mx-auto max-w-[1180px] space-y-4 ledger-animate-in">
      <div className="ledger-surface flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div className="min-w-0">
          <Link href="/ops" className="ledger-link text-sm">
            ← {t(locale, "ops.review.back")}
          </Link>
          <h1 className="mt-1 font-display text-[30px] font-semibold tracking-[-0.03em] text-desk-ink">
            {data.applicant_name || t(locale, "ops.common.unknown")}
          </h1>
          <p className="mt-0.5 font-mono text-xs text-desk-muted">
            {data.loan_id || t(locale, "ops.common.unknown")} · APP-{String(data.application_id).padStart(4, "0")}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <LedgerStamp
            tone={
              opsStatus === "needs_review"
                ? "warn"
                : opsStatus === "clean"
                  ? "ok"
                  : opsStatus === "failed"
                    ? "danger"
                    : "electric"
            }
          >
            {t(locale, `ops.review.status.${opsStatus}`)}
          </LedgerStamp>
          <button type="button" onClick={() => void ops.refetch()} className="ledger-btn ledger-btn--outline !min-h-[36px] !px-3 !text-xs">
            {t(locale, "ops.review.refresh")}
          </button>
        </div>
      </div>

      {opsStatus === "processing" ? (
        <section className="ledger-hero px-5 py-4" role="status" aria-live="polite">
          <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-[color:var(--electric)]">
            {t(locale, "ops.review.processing")}
          </p>
          <p className="mt-2 text-sm text-[color:var(--hero-muted)]">{t(locale, "ops.review.processingDetail")}</p>
          <div
            className="mt-3 h-2 overflow-hidden rounded-full bg-white/15"
            role="progressbar"
            aria-valuenow={Math.round(percentage)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={t(locale, "ops.review.processing")}
          >
            <div className="h-full rounded-full bg-[color:var(--electric)] transition-all" style={{ width: `${percentage}%` }} />
          </div>
          <p className="mt-1 font-mono text-xs text-[color:var(--hero-muted)]">
            {Math.round(percentage)}% {t(locale, "ops.review.progress")}
          </p>
        </section>
      ) : null}

      {opsStatus === "failed" && failureReason ? (
        <p role="alert" className="rounded-desk border border-[color:var(--danger)] bg-[color:var(--danger-muted)] px-4 py-3 text-sm font-semibold text-desk-danger">
          {failureReason}
        </p>
      ) : null}

      {opsStatus === "needs_review" && activeFinding ? (
        <section className="ledger-hero px-5 py-5" aria-label={t(locale, "ops.review.nextAction")}>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div className="min-w-0">
              <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-[color:var(--electric)]">
                {t(locale, "ops.review.nextAction")}
              </p>
              <h2 className="mt-2 font-display text-[28px] font-semibold text-[color:var(--hero-text)]">
                {pickText(activeFinding.title, locale)}
              </h2>
              <p className="mt-2 text-sm text-[color:var(--hero-muted)]">
                {activeFinding.severity} · {t(locale, "ops.evidence.pageOf")}{" "}
                {activeFinding.pages[0] ?? activeFinding.evidence?.page ?? "—"} ·{" "}
                {opsFindingExplanation(activeFinding, locale)}
              </p>
            </div>
            <div className="flex flex-wrap items-end gap-3">
              <div className="text-right">
                <p className="font-display text-4xl font-semibold text-[color:var(--hero-text)]">{openFindings.length}</p>
                <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-[color:var(--hero-muted)]">
                  {t(locale, "ops.review.openStamp")}
                </p>
              </div>
              <button
                type="button"
                className="ledger-btn ledger-btn--ghost"
                onClick={() => openWizardForFinding(activeFinding)}
              >
                {t(locale, "ops.review.openEvidence")}
              </button>
              <button type="button" className="ledger-btn ledger-btn--electric" onClick={() => markOk(activeFinding)}>
                {t(locale, "ops.review.markOk")}
              </button>
            </div>
          </div>
        </section>
      ) : null}

      {opsStatus === "clean" || (opsStatus === "needs_review" && openFindings.length === 0) ? (
        <section className="ledger-hero px-5 py-4">
          <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-[color:var(--electric)]">
            {t(locale, "ops.review.readyToClose")}
          </p>
          <p className="mt-2 text-sm text-[color:var(--hero-muted)]">{t(locale, "ops.review.readyDetail")}</p>
        </section>
      ) : null}

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.45fr)_minmax(300px,.85fr)]">
        <section aria-labelledby="ops-findings-heading" className="space-y-3">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-desk-danger">
                {t(locale, "ops.review.starOfReview")}
              </p>
              <h2 id="ops-findings-heading" className="font-display text-[28px] font-semibold text-desk-ink">
                {t(locale, "ops.review.findings")}
              </h2>
            </div>
            <LedgerStamp tone="danger">
              {openFindings.length} {t(locale, "ops.review.openStamp")}
            </LedgerStamp>
          </div>
          <div className="rounded-desk border border-[color:var(--border)] bg-[color:var(--surface)] p-3 ledger-rail-danger">
            <FindingsList
              findings={findings}
              activeCode={activeFinding?.code ?? null}
              resolvedCodes={resolvedCodes}
              onOpenEvidence={(finding) => openWizardForFinding(finding)}
            />
          </div>
          <PagesToVerifyChips
            rows={data.pages_to_verify}
            onOpenPage={(page) => setWizard({ kind: "page", page })}
          />
        </section>

        <OpsChecklist
          rows={data.checklist.rows}
          applicationId={applicationId}
          counts={{
            found: data.checklist.found,
            missing: data.checklist.missing,
            not_checked: data.checklist.not_checked,
          }}
          summary={pickText(data.summary, locale)}
          onOpenPage={(page) => setWizard({ kind: "page", page })}
        />
      </div>

      <OpsWorkflowPanel applicationId={applicationId} onOpenPage={(page) => setWizard({ kind: "page", page })} />
    </div>
  );
}
