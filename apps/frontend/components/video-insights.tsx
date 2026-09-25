"use client";
import { useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  Clapperboard,
  Eye,
  Hand,
  Heart,
  MessageCircle,
  RefreshCw,
  Share2,
  Sparkles,
  Timer,
  Trophy,
  UserPlus,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  api,
  Comparison,
  date,
  InsightVideo,
  number,
  TopVideos,
  VideoAnalysis,
  WatchResult,
  WatchState,
} from "@/lib/types";
import { Badge, Empty } from "./ui";

const PERIODS = [
  ["day", "Day"],
  ["week", "Week"],
  ["month", "Month"],
  ["year", "Year"],
] as const;
type Period = (typeof PERIODS)[number][0];

const pct = (v: number | null | undefined) =>
  v == null ? "—" : Math.round(v * 100) + "%";
const day = (iso: string) =>
  new Date(iso + "T12:00:00Z").toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
  });
const engine = (e: string) => (e === "opus" ? "OpusClip" : "Vizard");
const regions =
  typeof Intl !== "undefined" && "DisplayNames" in Intl
    ? new Intl.DisplayNames(["en"], { type: "region" })
    : null;
const country = (code: string) => {
  try {
    return regions?.of(code) || code;
  } catch {
    return code;
  }
};
const tooltipStyle = {
  background: "#171c22",
  border: "1px solid #333d45",
  borderRadius: 10,
  color: "#e8eee3",
};
const message = (e: unknown) =>
  e instanceof Error ? e.message : "Could not load YouTube analytics";

export function VideoInsights() {
  const [videos, setVideos] = useState<InsightVideo[]>([]);
  const [selected, setSelected] = useState("");
  const breakdown = useRef<HTMLElement>(null);

  useEffect(() => {
    api<{ videos: InsightVideo[] }>("/insights/videos")
      .then((r) => {
        setVideos(r.videos);
        const best = [...r.videos].sort(
          (a, b) => (b.views ?? -1) - (a.views ?? -1),
        )[0];
        if (best) setSelected((current) => current || best.video_id);
      })
      .catch(() => setVideos([]));
  }, []);

  const pick = (id: string) => {
    setSelected(id);
    breakdown.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <>
      <TopVideosPanel selected={selected} onPick={pick} />
      <ComparePanel selected={selected} onPick={pick} />
      <section ref={breakdown} className="vi-anchor">
        <VideoBreakdown
          videos={videos}
          selected={selected}
          onSelect={setSelected}
        />
      </section>
    </>
  );
}

const COMPARE_ROWS = 12;

function ComparePanel({
  selected,
  onPick,
}: {
  selected: string;
  onPick: (id: string) => void;
}) {
  const [data, setData] = useState<Comparison | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [showAll, setShowAll] = useState(false);

  const load = (refresh = false) => {
    setLoading(true);
    setError("");
    api<Comparison>(`/insights/compare${refresh ? "?refresh=true" : ""}`)
      .then(setData)
      .catch((e) => setError(message(e)))
      .finally(() => setLoading(false));
  };
  useEffect(() => load(), []);

  const rows = data
    ? showAll
      ? data.videos
      : data.videos.slice(0, COMPARE_ROWS)
    : [];

  return (
    <section className="panel section-spaced">
      <div className="panel-heading vi-heading">
        <div>
          <h2>Why some videos took off</h2>
          <p>
            Every video side by side: where its views came from and how viewers
            reacted.
          </p>
        </div>
        <button
          className="icon-button"
          onClick={() => load(true)}
          disabled={loading}
          aria-label="Refresh the comparison from YouTube"
        >
          <RefreshCw size={15} className={loading ? "vi-spin" : ""} />
        </button>
      </div>
      <div className="vi-body">
        {error ? (
          <div className="inline-error" role="alert">
            {error}
          </div>
        ) : !data ? (
          <p className="vi-muted">Comparing all your videos…</p>
        ) : (
          <>
            <div className="vi-card vi-notes">
              <h4>What the numbers say</h4>
              <ul>
                {data.findings.map((note) => (
                  <li key={note}>
                    <Sparkles size={14} />
                    <span>{note}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="vi-table-wrap">
              <table className="vi-table">
                <thead>
                  <tr>
                    <th>Video</th>
                    <th className="num">Views</th>
                    <th className="num">From Shorts feed</th>
                    <th className="num">From search</th>
                    <th className="num">Stayed</th>
                    <th className="num">Watched</th>
                    <th className="num">Length</th>
                    <th>Posted</th>
                    <th className="num">Posted that day</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((v) => (
                    <tr
                      key={v.video_id}
                      className={
                        (v.feed_tested ? "tested " : "") +
                        (v.video_id === selected ? "current" : "")
                      }
                    >
                      <td>
                        <div className="vi-table-video">
                          <button
                            onClick={() => onPick(v.video_id)}
                            title="Show this video's breakdown"
                          >
                            <img src={v.thumbnail} alt="" />
                            <span>{v.title}</span>
                          </button>
                          {v.feed_tested && (
                            <Badge kind="approved">Shown in feed</Badge>
                          )}
                        </div>
                      </td>
                      <td className="num">
                        <b>{number(v.views)}</b>
                      </td>
                      <td className="num">{number(v.feed_views)}</td>
                      <td className="num">{number(v.search_views)}</td>
                      <td className="num">{pct(v.stayed_rate)}</td>
                      <td className="num">
                        {v.average_view_percentage == null
                          ? "—"
                          : Math.round(v.average_view_percentage) + "%"}
                      </td>
                      <td className="num">{Math.round(v.duration)}s</td>
                      <td>{date(v.published_at)}</td>
                      <td className="num">{v.posted_same_day}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {data.videos.length > COMPARE_ROWS && (
              <button
                className="button vi-show-all"
                onClick={() => setShowAll((s) => !s)}
              >
                {showAll
                  ? "Show fewer"
                  : `Show all ${data.videos.length} videos`}
              </button>
            )}
            <p className="vi-note">
              {data.note} “Shown in feed” means the Shorts feed sent it at least
              20 views.
            </p>
          </>
        )}
      </div>
    </section>
  );
}

function TopVideosPanel({
  selected,
  onPick,
}: {
  selected: string;
  onPick: (id: string) => void;
}) {
  const [period, setPeriod] = useState<Period>("week");
  const [data, setData] = useState<TopVideos | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const request = useRef(0);

  const load = (refresh = false) => {
    const id = ++request.current;
    setLoading(true);
    setError("");
    if (!refresh) setData(null);
    api<TopVideos>(
      `/insights/top?period=${period}${refresh ? "&refresh=true" : ""}`,
    )
      .then((r) => id === request.current && setData(r))
      .catch((e) => {
        if (id !== request.current) return;
        setData(null);
        setError(message(e));
      })
      .finally(() => id === request.current && setLoading(false));
  };
  useEffect(() => load(), [period]);

  return (
    <section className="panel section-spaced">
      <div className="panel-heading vi-heading">
        <div>
          <h2>Top videos</h2>
          <p>
            Most-watched on YouTube
            {data ? ` · ${day(data.start)} – ${day(data.end)}` : ""}
          </p>
        </div>
        <div className="vi-toolbar">
          <div className="filter-chips vi-chips" role="tablist">
            {PERIODS.map(([id, label]) => (
              <button
                key={id}
                role="tab"
                aria-selected={period === id}
                className={period === id ? "active" : ""}
                onClick={() => setPeriod(id)}
              >
                {label}
              </button>
            ))}
          </div>
          <button
            className="icon-button"
            onClick={() => load(true)}
            disabled={loading}
            aria-label="Refresh top videos from YouTube"
          >
            <RefreshCw size={15} className={loading ? "vi-spin" : ""} />
          </button>
        </div>
      </div>
      <div className="vi-body">
        {error ? (
          <div className="inline-error" role="alert">
            {error}
          </div>
        ) : loading && !data ? (
          <p className="vi-muted">Asking YouTube for this period…</p>
        ) : data && data.videos.length ? (
          <ol className="vi-top-list">
            {data.videos.map((v, i) => (
              <li key={v.video_id}>
                <button
                  className={
                    "vi-top-row " + (v.video_id === selected ? "selected" : "")
                  }
                  aria-pressed={v.video_id === selected}
                  onClick={() => onPick(v.video_id)}
                  disabled={!v.published_by_clipbot}
                  title={
                    v.published_by_clipbot
                      ? "Show this video's breakdown"
                      : "Not uploaded by ClipBot"
                  }
                >
                  <span className={"vi-rank " + (i === 0 ? "first" : "")}>
                    {i === 0 ? <Trophy size={14} /> : i + 1}
                  </span>
                  <img src={v.thumbnail} alt="" className="vi-thumb" />
                  <span className="vi-top-title">
                    <b>{v.title}</b>
                    {v.published_at && (
                      <small>Posted {date(v.published_at)}</small>
                    )}
                  </span>
                  <span className="vi-top-metric">
                    <b>{number(v.views)}</b>
                    <small>views</small>
                  </span>
                  <span className="vi-top-metric vi-extra">
                    <b>{pct(v.stayed_rate)}</b>
                    <small>stayed</small>
                  </span>
                  <span className="vi-top-metric vi-extra">
                    <b>
                      {v.average_view_percentage == null
                        ? "—"
                        : Math.round(v.average_view_percentage) + "%"}
                    </b>
                    <small>watched</small>
                  </span>
                </button>
              </li>
            ))}
          </ol>
        ) : (
          <Empty
            title="Nothing reported for this period yet"
            text={
              period === "day"
                ? "YouTube hasn't reported views for the last two days yet. Its analytics run 1–2 days behind, so check the week view."
                : "No views were reported in this period."
            }
          />
        )}
        {data && <p className="vi-note">{data.note}</p>}
      </div>
    </section>
  );
}

function VideoBreakdown({
  videos,
  selected,
  onSelect,
}: {
  videos: InsightVideo[];
  selected: string;
  onSelect: (id: string) => void;
}) {
  const [data, setData] = useState<VideoAnalysis | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    if (!selected) return;
    let current = true;
    setLoading(true);
    setError("");
    api<VideoAnalysis>(
      `/insights/videos/${encodeURIComponent(selected)}${reload ? "?refresh=true" : ""}`,
    )
      .then((r) => current && setData(r))
      .catch((e) => {
        if (!current) return;
        setData(null);
        setError(message(e));
      })
      .finally(() => current && setLoading(false));
    return () => {
      current = false;
    };
  }, [selected, reload]);

  const ordered = [...videos].sort((a, b) => (b.views ?? -1) - (a.views ?? -1));
  const shown = data && data.video.video_id === selected ? data : null;

  return (
    <section className="panel section-spaced">
      <div className="panel-heading vi-heading">
        <div>
          <h2>Video breakdown</h2>
          <p>Why one video did better or worse than the rest.</p>
        </div>
        <div className="vi-toolbar">
          <label className="vi-select">
            <span className="sr-only">Choose a video</span>
            <select
              value={selected}
              onChange={(e) => onSelect(e.target.value)}
              disabled={!videos.length}
            >
              {!videos.length && (
                <option value="">No YouTube videos yet</option>
              )}
              {ordered.map((v) => (
                <option key={v.video_id} value={v.video_id}>
                  {v.title}
                  {v.views != null ? ` · ${number(v.views)} views` : ""}
                </option>
              ))}
            </select>
          </label>
          <button
            className="icon-button"
            onClick={() => setReload((n) => n + 1)}
            disabled={loading || !selected}
            aria-label="Refresh this video from YouTube"
          >
            <RefreshCw size={15} className={loading ? "vi-spin" : ""} />
          </button>
        </div>
      </div>
      <div className="vi-body">
        {error ? (
          <div className="inline-error" role="alert">
            {error}
          </div>
        ) : !selected ? (
          <Empty
            title="No YouTube videos yet"
            text="Once ClipBot publishes to YouTube, pick any video here to see how it performed."
          />
        ) : !shown ? (
          <p className="vi-muted">
            Pulling this video&rsquo;s numbers from YouTube…
          </p>
        ) : (
          <Analysis data={shown} />
        )}
      </div>
    </section>
  );
}

function Analysis({ data }: { data: VideoAnalysis }) {
  const { video, summary, live } = data;
  const views = live.viewCount ?? summary.views;
  const typical =
    data.typical_views != null && views >= 2 * Math.max(data.typical_views, 1)
      ? `${Math.round(views / Math.max(data.typical_views, 1))}× your typical video`
      : `${number(summary.views)} counted in YouTube Analytics`;
  const stats = [
    { label: "Views", value: number(views), detail: typical, icon: Eye },
    {
      label: "Stayed past the opening",
      value: pct(summary.stayed_rate),
      detail: "Didn't swipe away straight away",
      icon: Hand,
    },
    {
      label: "Average watched",
      value:
        summary.average_view_percentage == null
          ? "—"
          : Math.round(summary.average_view_percentage) + "%",
      detail:
        summary.average_view_duration == null
          ? "Not reported yet"
          : `${Math.round(summary.average_view_duration)}s of ${Math.round(video.duration)}s`,
      icon: Timer,
    },
    {
      label: "Likes",
      value: number(live.likeCount ?? summary.likes),
      detail: "Live from YouTube",
      icon: Heart,
    },
    {
      label: "Comments",
      value: number(live.commentCount ?? summary.comments),
      detail: "Live from YouTube",
      icon: MessageCircle,
    },
    {
      label: "Shares",
      value: number(summary.shares),
      detail: "YouTube Analytics",
      icon: Share2,
    },
    {
      label: "New subscribers",
      value: number(summary.subscribers_gained),
      detail: "From this video",
      icon: UserPlus,
    },
  ];
  const curve = data.retention.map((p) => ({
    second: p.second,
    watching: Math.round(p.watching * 1000) / 10,
  }));
  const topCountry = Math.max(1, ...data.countries.map((c) => c.views));

  return (
    <div className="vi-analysis">
      <div className="vi-head">
        <img src={video.thumbnail} alt="" className="vi-head-thumb" />
        <div>
          <h3>{video.title}</h3>
          <p className="vi-muted">
            Posted {date(video.published_at)} · {engine(video.engine)} ·{" "}
            {Math.round(video.duration)}s
          </p>
          <div className="vi-head-actions">
            {video.removed ? (
              <Badge kind="failed">No longer on YouTube</Badge>
            ) : (
              <a href={video.url} target="_blank" rel="noreferrer">
                Open on YouTube <ArrowUpRight size={13} />
              </a>
            )}
          </div>
          {video.opening && (
            <blockquote className="vi-quote">
              <span>How it opens</span>“{video.opening}…”
            </blockquote>
          )}
        </div>
      </div>

      <div className="vi-stats">
        {stats.map((s) => (
          <article className="vi-stat" key={s.label}>
            <div>
              {s.label}
              <s.icon size={14} />
            </div>
            <strong>{s.value}</strong>
            <small>{s.detail}</small>
          </article>
        ))}
      </div>

      <WatchPanel videoId={video.video_id} />

      <div className="vi-card vi-notes">
        <h4>What stands out</h4>
        <ul>
          {data.observations.map((note) => (
            <li key={note}>
              <Sparkles size={14} />
              <span>{note}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="vi-grid">
        <div className="vi-card">
          <h4>Where viewers dropped off</h4>
          {curve.length ? (
            <div
              className="vi-chart"
              role="img"
              aria-label={`Share of viewers still watching over ${Math.round(video.duration)} seconds`}
            >
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart
                  data={curve}
                  margin={{ left: -18, right: 10, top: 10 }}
                >
                  <defs>
                    <linearGradient
                      id="viRetention"
                      x1="0"
                      y1="0"
                      x2="0"
                      y2="1"
                    >
                      <stop
                        offset="0%"
                        stopColor="#c3f879"
                        stopOpacity={0.25}
                      />
                      <stop offset="100%" stopColor="#c3f879" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid
                    stroke="#242930"
                    vertical={false}
                    strokeDasharray="3 6"
                  />
                  <XAxis
                    dataKey="second"
                    type="number"
                    domain={[0, "dataMax"]}
                    tickFormatter={(s) => `${Math.round(s)}s`}
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: "#8e969f", fontSize: 10 }}
                  />
                  <YAxis
                    tickFormatter={(v) => `${v}%`}
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: "#76808b", fontSize: 10 }}
                  />
                  <ReferenceLine
                    y={100}
                    stroke="#4a5560"
                    strokeDasharray="4 4"
                  />
                  <Tooltip
                    contentStyle={tooltipStyle}
                    labelFormatter={(s) => `${Number(s).toFixed(1)}s in`}
                    formatter={(v) => [`${v}%`, "Still watching"]}
                  />
                  <Area
                    isAnimationActive={false}
                    type="monotone"
                    dataKey="watching"
                    stroke="#c3f879"
                    strokeWidth={2}
                    fill="url(#viRetention)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="vi-muted">
              YouTube shares a drop-off curve once a video has enough views.
            </p>
          )}
          <small className="vi-caption">
            Over 100% means people replayed that part.
          </small>
        </div>

        <div className="vi-card">
          <h4>Views per day</h4>
          {data.daily.some((d) => d.views) ? (
            <div className="vi-chart" role="img" aria-label="Views per day">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={data.daily}
                  margin={{ left: -18, right: 10, top: 10 }}
                >
                  <CartesianGrid
                    stroke="#242930"
                    vertical={false}
                    strokeDasharray="3 6"
                  />
                  <XAxis
                    dataKey="date"
                    tickFormatter={day}
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: "#8e969f", fontSize: 10 }}
                  />
                  <YAxis
                    tickFormatter={number}
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: "#76808b", fontSize: 10 }}
                  />
                  <Tooltip
                    contentStyle={tooltipStyle}
                    cursor={{ fill: "#1d242c" }}
                    labelFormatter={(d) => day(String(d))}
                    formatter={(v) => [number(Number(v)), "Views"]}
                  />
                  <Bar
                    dataKey="views"
                    fill="#c3f879"
                    radius={[4, 4, 0, 0]}
                    isAnimationActive={false}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="vi-muted">No daily views reported yet.</p>
          )}
          <small className="vi-caption">
            Days follow YouTube&rsquo;s US Pacific time.
          </small>
        </div>

        <div className="vi-card">
          <h4>Where views came from</h4>
          {data.traffic.length ? (
            <ul className="vi-bars">
              {data.traffic.map((t) => (
                <li key={t.source}>
                  <span>{t.label}</span>
                  <i
                    style={{ width: `${Math.max(2, (t.share ?? 0) * 100)}%` }}
                  />
                  <b>
                    {pct(t.share)} <small>{number(t.views)}</small>
                  </b>
                </li>
              ))}
            </ul>
          ) : (
            <p className="vi-muted">No traffic sources reported yet.</p>
          )}
        </div>

        <div className="vi-card">
          <h4>Top countries</h4>
          {data.countries.length ? (
            <ul className="vi-bars">
              {data.countries.map((c) => (
                <li key={c.country}>
                  <span>{country(c.country)}</span>
                  <i
                    style={{
                      width: `${Math.max(2, (c.views / topCountry) * 100)}%`,
                    }}
                  />
                  <b>{number(c.views)}</b>
                </li>
              ))}
            </ul>
          ) : (
            <p className="vi-muted">No country data reported yet.</p>
          )}
        </div>
      </div>

      <p className="vi-note">
        {data.note} Analytics window {day(data.range.start)} –{" "}
        {day(data.range.end)}.
      </p>
    </div>
  );
}

const MOMENT_LABEL: Record<WatchResult["moments"][number]["kind"], string> = {
  hook: "Hook",
  payoff: "Payoff",
  drop_off: "Viewers left",
  rewatch: "Replayed",
  slow: "Slow patch",
  other: "Moment",
};
const HOOK_BADGE: Record<WatchResult["hook"]["rating"], string> = {
  strong: "approved",
  mixed: "reserve",
  weak: "failed",
};
const toSeconds = (time: string) => {
  const match = time.match(/(\d+):(\d{2})/);
  return match ? Number(match[1]) * 60 + Number(match[2]) : 0;
};

function WatchPanel({ videoId }: { videoId: string }) {
  const [state, setState] = useState<WatchState | null>(null);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);
  const shown = useRef(videoId);
  shown.current = videoId;
  const path = `/insights/videos/${encodeURIComponent(videoId)}/watch`;
  const working = state?.status === "queued" || state?.status === "running";

  useEffect(() => {
    setState(null);
    setError("");
    api<WatchState>(path)
      .then((s) => shown.current === videoId && setState(s))
      .catch((e) => shown.current === videoId && setError(message(e)));
  }, [path, videoId]);

  useEffect(() => {
    if (!working) return;
    const timer = setInterval(() => {
      api<WatchState>(path)
        .then((s) => shown.current === videoId && setState(s))
        .catch(() => undefined);
    }, 4000);
    return () => clearInterval(timer);
  }, [working, path, videoId]);

  const start = () => {
    setStarting(true);
    setError("");
    api<WatchState>(path, {})
      .then((s) => shown.current === videoId && setState(s))
      .catch((e) => setError(message(e)))
      .finally(() => setStarting(false));
  };

  const action = !state?.configured ? null : working ? (
    <button className="button" disabled>
      <RefreshCw size={14} className="vi-spin" /> Watching…
    </button>
  ) : state.status === "done" ? (
    <button className="button" onClick={start} disabled={starting}>
      Re-analyse
    </button>
  ) : (
    <button className="button primary" onClick={start} disabled={starting}>
      {state.status === "none" ? "Analyse this clip" : "Try again"}
    </button>
  );

  return (
    <div className="vi-card vi-watch">
      <div className="vi-watch-head">
        <h4>
          <Clapperboard size={15} /> Gemini watched this clip
        </h4>
        {action}
      </div>
      {error && (
        <div className="inline-error" role="alert">
          {error}
        </div>
      )}
      {!state && !error ? (
        <p className="vi-muted">Checking for a saved analysis…</p>
      ) : state && !state.configured ? (
        <p className="vi-muted">
          Add <code>GEMINI_API_KEY</code> to your <code>.env</code> (free at
          aistudio.google.com/apikey), then restart ClipBot to let Gemini watch
          your clips and explain why they did well or badly.
        </p>
      ) : state ? (
        <>
          {state.status === "none" && (
            <p className="vi-muted">
              Gemini watches the actual clip, sound included, alongside its
              YouTube numbers, then explains the hook, where viewers left and
              what to change. Takes about 10–60 seconds.
            </p>
          )}
          {working && (
            <p className="vi-muted" role="status">
              {state.error ||
                "Gemini is watching the clip. This usually takes 10–60 seconds."}
            </p>
          )}
          {state.status === "failed" && state.error && (
            <div className="inline-error" role="alert">
              {state.error}
            </div>
          )}
          {state.status === "stalled" && (
            <p className="vi-muted">
              The last analysis was interrupted, probably because ClipBot was
              closed. Start it again.
            </p>
          )}
          {state.result && (
            <WatchResultView result={state.result} videoId={videoId} />
          )}
          {state.result && state.updated_at && (
            <p className="vi-note">
              Analysed by {state.model || "Gemini"} · {date(state.updated_at)}.
              On Google&rsquo;s free tier, Google may use the clips you send to
              improve its products.
            </p>
          )}
        </>
      ) : null}
    </div>
  );
}

function WatchResultView({
  result,
  videoId,
}: {
  result: WatchResult;
  videoId: string;
}) {
  return (
    <div className="vi-watch-body">
      <p className="vi-watch-summary">{result.summary}</p>

      <div className="vi-watch-hook">
        <Badge kind={HOOK_BADGE[result.hook.rating] || "neutral"}>
          {result.hook.rating} hook
        </Badge>
        <div>
          <b>{result.hook.first_seconds}</b>
          <p>{result.hook.why}</p>
        </div>
      </div>

      {result.moments.length > 0 && (
        <ol className="vi-timeline">
          {result.moments.map((m, i) => (
            <li key={m.time + i} className={"kind-" + m.kind}>
              <a
                className="vi-time"
                href={`https://www.youtube.com/watch?v=${encodeURIComponent(videoId)}&t=${toSeconds(m.time)}s`}
                target="_blank"
                rel="noreferrer"
                title="Open this moment on YouTube"
              >
                {m.time}
              </a>
              <div>
                <span className="vi-kind">
                  {MOMENT_LABEL[m.kind] || "Moment"}
                </span>
                <p>{m.happening}</p>
                <small>{m.effect}</small>
              </div>
            </li>
          ))}
        </ol>
      )}

      <div className="vi-grid">
        <WatchList title="What worked" items={result.worked} tone="good" />
        <WatchList title="What hurt it" items={result.hurt} tone="bad" />
      </div>

      {result.next_time.length > 0 && (
        <div className="vi-watch-next">
          <h5>Try next time</h5>
          <ol>
            {result.next_time.map((tip) => (
              <li key={tip}>{tip}</li>
            ))}
          </ol>
        </div>
      )}

      <p className="vi-watch-luck">
        <b>Content or luck?</b> {result.luck_vs_content}
      </p>
    </div>
  );
}

function WatchList({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone: "good" | "bad";
}) {
  if (!items.length) return null;
  return (
    <div className={"vi-watch-list " + tone}>
      <h5>{title}</h5>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
