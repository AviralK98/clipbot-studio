import Dashboard from "@/components/dashboard";
import { notFound } from "next/navigation";
export default async function Page({
  params,
}: {
  params: Promise<{ view: string }>;
}) {
  const { view } = await params;
  if (
    ![
      "sources",
      "clips",
      "queue",
      "analytics",
      "insights",
      "connections",
      "settings",
    ].includes(view)
  )
    notFound();
  return <Dashboard view={view} />;
}
