import Dashboard from "@/components/dashboard";
import { notFound } from "next/navigation";

const VIEWS = [
  "sources",
  "clips",
  "queue",
  "analytics",
  "insights",
  "connections",
  "settings",
];

// Every page is known up front, so the desktop app's plain-files build can include them all.
export const dynamicParams = false;
export function generateStaticParams() {
  return VIEWS.map((view) => ({ view }));
}

export default async function Page({
  params,
}: {
  params: Promise<{ view: string }>;
}) {
  const { view } = await params;
  if (!VIEWS.includes(view)) notFound();
  return <Dashboard view={view} />;
}
