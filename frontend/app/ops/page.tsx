"use client";

import { useRouter } from "next/navigation";

import { PortalWorklist } from "@/components/portal/PortalWorklist";

export default function OpsWorklistPage() {
  const router = useRouter();
  return (
    <PortalWorklist
      chrome={false}
      onOpen={(applicationId) => router.push(`/ops/applications/${applicationId}`)}
    />
  );
}
