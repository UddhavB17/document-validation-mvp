"use client";

import { ErrorMessage, InfoMessage, LoadingMessage } from "@/components/Message";
import { Metric } from "@/components/Metric";
import { PageHeader } from "@/components/PageHeader";
import { SortableTable } from "@/components/SortableTable";
import { useActivityToday } from "@/lib/queries";
import { StatusBadge } from "@/components/StatusBadge";

export default function ActivityPage() {
  const activity = useActivityToday();

  return (
    <div className="space-y-6 max-w-[1600px] mx-auto animate-fade-in">
      <PageHeader title="My Activity" description="Decisions recorded today by the active reviewer profile." />
      {activity.isLoading ? <LoadingMessage /> : null}
      {activity.isError ? <ErrorMessage message="Unable to load reviewer activity logs." /> : null}
      {activity.data ? (
        activity.data.rows.length === 0 ? (
          <InfoMessage message="No reviewer decisions recorded today." />
        ) : (
          <div className="space-y-6">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <Metric label="Files reviewed today" value={activity.data.total} />
              <Metric label="Accepted" value={activity.data.accepted} />
              <Metric label="Overridden" value={activity.data.overridden} />
              <Metric label="Sent back" value={activity.data.sent_back} />
            </div>
            <SortableTable
              rows={activity.data.rows}
              columns={[
                {
                  key: "id",
                  header: "Decision ID",
                  value: (row) => <span className="font-mono text-slate-800 font-bold">DEC-{String(row.id).padStart(4, "0")}</span>,
                  sortValue: (row) => row.id
                },
                {
                  key: "application",
                  header: "Application ID",
                  value: (row) => (
                    <LinkOrText applicationId={row.application_id}>
                      APP-{String(row.application_id).padStart(4, "0")}
                    </LinkOrText>
                  ),
                  sortValue: (row) => row.application_id
                },
                {
                  key: "loan",
                  header: "Loan ID",
                  value: (row) => <span className="font-mono font-bold text-slate-850 text-[13px]">{row.loan_id}</span>,
                  sortValue: (row) => row.loan_id
                },
                {
                  key: "decision",
                  header: "Decision",
                  value: (row) => <StatusBadge status={row.decision} />,
                  sortValue: (row) => row.decision
                },
                {
                  key: "decided",
                  header: "Decided At",
                  value: (row) => <span className="font-mono text-slate-500 text-[11.5px]">{row.decided_at}</span>,
                  sortValue: (row) => row.decided_at
                },
              ]}
            />
          </div>
        )
      ) : null}
    </div>
  );
}

function LinkOrText({ applicationId, children }: { applicationId: number; children: React.ReactNode }) {
  return (
    <Link
      href={`/applications/${applicationId}`}
      className="font-mono font-bold text-[#2B4C7E] hover:text-[#1E3559] hover:underline transition-all"
    >
      {children}
    </Link>
  );
}

import Link from "next/link";
