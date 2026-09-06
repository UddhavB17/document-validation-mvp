import { redirect } from "next/navigation";

export default function LegacyApplicationRedirect({
  params,
  searchParams,
}: {
  params: { id: string };
  searchParams?: { tab?: string };
}) {
  const tab = searchParams?.tab ? `?tab=${encodeURIComponent(searchParams.tab)}` : "";
  redirect(`/admin/applications/${params.id}${tab}`);
}
