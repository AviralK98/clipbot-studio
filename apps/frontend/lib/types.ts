export type Clip = {
  id: string;
  title: string;
  source: string;
  source_video_id: string;
  provider: string;
  duration: number;
  overall_score: number | null;
  topic: string;
  status: string;
  tier: string | null;
  demo: boolean;
  transcript: string;
  reason: string;
  policy_flags: string[];
  storage_key: string | null;
  duplicate_of: string | null;
  hook_style: string;
  metadata_json: Record<string, unknown>;
  evaluation?: { scores: Record<string, number>; reason: string } | null;
};
export type Source = {
  id: string;
  name: string;
  url: string;
  kind: string;
  authorization_type: string;
  authorization_note: string;
  authorized_platforms: string[];
  category: string;
  enabled: boolean;
  routing: string;
  demo: boolean;
  last_checked_at: string | null;
  last_error: string | null;
};
export type Account = {
  id: string;
  name: string;
  platform: string;
  enabled: boolean;
  demo: boolean;
  external_id: string;
  daily_limit: number;
};
export type Job = {
  id: string;
  kind: string;
  status: string;
  attempts: number;
  error: string | null;
  created_at: string;
  payload: Record<string, string>;
};
export type Post = {
  id: string;
  clip_id: string;
  title: string;
  account: string;
  platform: string;
  status: string;
  scheduled_at: string;
  demo: boolean;
  error: string | null;
  publication: { id: string; url: string | null; published_at: string } | null;
};
export type Settings = {
  autopilot: boolean;
  stop_all_posting: boolean;
  timezone: string;
  posting_times: string[];
  daily_limit: number;
  min_interval: number;
  thresholds: Record<string, number>;
  policy_filters: string[];
  learning_enabled: boolean;
  last_heartbeat: string | null;
};
export type Breakdown = {
  dimension: string;
  label: string;
  published: number;
  median_views: number;
  watch_completion: number | null;
  shares_per_1000: number | null;
  followers_per_1000: number | null;
  engagement_rate: number | null;
};
export type Studio = {
  demo_mode: boolean;
  settings: Settings;
  counts: Record<string, number>;
  sources: Source[];
  accounts: Account[];
  jobs: Job[];
  projects: {
    id: string;
    provider: string;
    external_id: string | null;
    status: string;
    error: string | null;
  }[];
  insights: {
    id: string;
    title: string;
    body: string;
    evidence: Record<string, unknown>;
  }[];
  strategy: {
    id: string;
    dimension: string;
    label: string;
    samples: number;
    median_views: number;
    weight: number;
  }[];
  integrations: {
    id: string;
    configured: boolean;
    variables: string[];
    detail: string;
  }[];
  limits: Record<string, number>;
  usage: { provider: string; cost: number; units: number }[];
  analytics: {
    views: number;
    views_today: number;
    views_7d: number;
    followers_gained: number;
    followers_available: boolean;
    trend: { date: string; views: number }[];
    breakdown: Breakdown[];
    snapshots: number;
    note: string;
  };
};
export async function api<T>(
  path: string,
  body?: unknown,
  method?: string,
): Promise<T> {
  const response = await fetch("/api" + path, {
    method: method || (body === undefined ? "GET" : "POST"),
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) {
    const detail =
      typeof data.detail === "string"
        ? data.detail
        : Array.isArray(data.detail)
          ? data.detail.map((e: { msg: string }) => e.msg).join("; ")
          : "Request failed";
    throw Object.assign(new Error(detail), { status: response.status });
  }
  return data as T;
}
export const number = (n: number | null | undefined) =>
  n == null
    ? "—"
    : new Intl.NumberFormat("en-GB", {
        notation: n >= 10000 ? "compact" : "standard",
        maximumFractionDigits: 1,
      }).format(n);
export const date = (value: string, zone = "Europe/London") =>
  new Date(value).toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: zone,
  });
