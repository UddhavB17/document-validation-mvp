import { redirect } from "next/navigation";

export default async function LegacyApplicationRedirect({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams?: Promise<{ tab?: string }>;
}) {
  const { id } = await params;
  const resolvedSearchParams = await searchParams;
  const tab = resolvedSearchParams?.tab ? `?tab=${encodeURIComponent(resolvedSearchParams.tab)}` : "";
  redirect(`/admin/applications/${id}${tab}`);
}
