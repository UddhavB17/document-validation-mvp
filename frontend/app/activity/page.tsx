"use client";

import { ErrorMessage, InfoMessage, LoadingMessage } from "@/components/Message";
import { Metric } from "@/components/Metric";
import { PageHeader } from "@/components/PageHeader";
import { SortableTable } from "@/components/SortableTable";
import { useActivityToday } from "@/lib/queries";

export default function ActivityPage() {
  const activity = useActivityToday();

  return (
    <>
      <PageHeader title="My Activity" description="Decisions recorded today" />
      {activity.isLoading ? <LoadingMessage /> : null}
      {activity.isError ? <ErrorMessage message="Unable to load activity." /> : null}
      {activity.data ? (
        activity.data.rows.length === 0 ? (
          <InfoMessage message="No reviewer decisions recorded today." />
        ) : (
          <div className="space-y-5">
            <div className="grid grid-cols-4 gap-3">
              <Metric label="Files reviewed today" value={activity.data.total} />
              <Metric label="Accepted" value={activity.data.accepted} />
              <Metric label="Overridden" value={activity.data.overridden} />
              <Metric label="Sent back" value={activity.data.sent_back} />
            </div>
            <SortableTable
              rows={activity.data.rows}
              columns={[
                { key: "id", header: "Decision ID", value: (row) => row.id, sortValue: (row) => row.id },
                { key: "application", header: "Application", value: (row) => row.application_id, sortValue: (row) => row.application_id },
                { key: "loan", header: "Loan ID", value: (row) => row.loan_id, sortValue: (row) => row.loan_id },
                { key: "decision", header: "Decision", value: (row) => row.decision, sortValue: (row) => row.decision },
                { key: "decided", header: "Decided At", value: (row) => row.decided_at, sortValue: (row) => row.decided_at },
              ]}
            />
          </div>
        )
      ) : null}
    </>
  );
}
