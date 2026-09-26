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
  account_id: string;
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
  recent_videos: RecentVideo[];
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
/** One setting on the keys screen. Secrets only say whether they're saved, never their value. */
export type ConfigField = {
  name: string;
  label: string;
  secret: boolean;
  saved: boolean;
  value: string | null;
  from_environment: boolean;
  choices?: string[];
};
export type AppConfig = {
  /** False when keys come from environment variables (.env, Docker), so the app can't change them. */
  editable: boolean;
  groups: {
    id: string;
    title: string;
    about: string;
    link?: string;
    fields: ConfigField[];
  }[];
  youtube: YouTubeConnection;
};
export type YouTubeConnection = {
  connected: boolean;
  status: "idle" | "waiting" | "connected" | "failed";
  message: string;
  url: string | null;
};
/** A recently added video and where it is in the clipping pipeline. */
export type RecentVideo = {
  id: string;
  title: string;
  url: string;
  thumbnail: string;
  duration: number;
  added_at: string;
  finished_at: string | null;
  stage: "sending" | "clipping" | "scoring" | "done" | "failed";
  problem: string | null;
  engines: {
    provider: string;
    name: string;
    project_id: string;
    external_id: string | null;
    status: string;
    problem: string | null;
    clips: number;
    /** The owner confirmed OpusClip finished; its clips are being imported. */
    confirmed: boolean;
    /** OpusClip can't notify ClipBot here, so the owner confirms when it's finished. */
    needs_confirmation: boolean;
  }[];
  /** Video files download after scoring; a clip can be posted once its file is saved. */
  files: { saved: number; pending: number; problem: string | null };
  clips: {
    found: number;
    scored: number;
    scoring: number;
    approved: number;
    review: number;
    rejected: number;
  };
};
export type InsightVideo = {
  video_id: string;
  title: string;
  published_at: string;
  clip_id: string;
  engine: string;
  duration: number;
  views: number | null;
  url: string;
  thumbnail: string;
};
export type VideoStats = {
  views: number;
  engaged_views: number | null;
  stayed_rate: number | null;
  average_view_percentage: number | null;
  average_view_duration: number | null;
  likes: number | null;
  comments?: number | null;
  shares: number | null;
  subscribers_gained: number | null;
};
export type TopVideos = {
  period: string;
  start: string;
  end: string;
  note: string;
  videos: (VideoStats & {
    video_id: string;
    title: string;
    published_at: string | null;
    thumbnail: string;
    url: string;
    published_by_clipbot: boolean;
    /** Views are YouTube's live count because Analytics hasn't reported this new video yet. */
    live_count: boolean;
  })[];
};
export type VideoAnalysis = {
  video: {
    video_id: string;
    title: string;
    url: string;
    thumbnail: string;
    published_at: string;
    engine: string;
    duration: number;
    opening: string;
    removed: boolean;
  };
  range: { start: string; end: string };
  live: {
    viewCount: number | null;
    likeCount: number | null;
    commentCount: number | null;
  };
  summary: VideoStats;
  typical_views: number | null;
  traffic: {
    source: string;
    label: string;
    views: number;
    share: number | null;
  }[];
  daily: { date: string; views: number; engaged_views: number | null }[];
  countries: { country: string; views: number }[];
  retention: {
    position: number;
    second: number;
    watching: number;
    relative: number | null;
  }[];
  observations: string[];
  note: string;
  fetched_at: string;
};
export type CompareVideo = {
  video_id: string;
  title: string;
  thumbnail: string;
  url: string;
  published_at: string;
  engine: string;
  duration: number;
  views: number;
  analytics_views: number;
  /** YouTube hasn't reported where this video's newest views came from yet. */
  sources_pending: boolean;
  feed_views: number;
  search_views: number;
  other_views: number;
  stayed_rate: number | null;
  average_view_percentage: number | null;
  posted_day: string;
  posted_same_day: number;
  upload_number: number;
  feed_tested: boolean;
};
export type Comparison = {
  start: string;
  end: string;
  videos: CompareVideo[];
  findings: string[];
  note: string;
};
export type WatchResult = {
  summary: string;
  hook: {
    first_seconds: string;
    rating: "strong" | "mixed" | "weak";
    why: string;
  };
  moments: {
    time: string;
    kind: "hook" | "payoff" | "drop_off" | "rewatch" | "slow" | "other";
    happening: string;
    effect: string;
  }[];
  worked: string[];
  hurt: string[];
  next_time: string[];
  luck_vs_content: string;
};
export type WatchState = {
  status: "none" | "queued" | "running" | "done" | "failed" | "stalled";
  configured: boolean;
  model?: string | null;
  result?: WatchResult | null;
  error?: string | null;
  updated_at?: string;
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
