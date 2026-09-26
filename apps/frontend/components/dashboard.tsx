"use client";
import { BulkActions } from "./bulk-actions";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  AudioLines,
  BarChart3,
  Bell,
  CalendarClock,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Clapperboard,
  Clock3,
  ExternalLink,
  Film,
  Layers,
  LayoutDashboard,
  Loader2,
  LogOut,
  Menu,
  Pause,
  Play,
  Plus,
  Radio,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Square,
  Upload,
  WandSparkles,
  X,
  Zap,
} from "lucide-react";
import {
  api,
  Clip,
  date,
  Job,
  number,
  Post,
  Source,
  Studio,
} from "@/lib/types";
import { Badge, ClipCard, Empty, Modal, ReachChart, Stat, Toggle } from "./ui";
import { PlatformCopy } from "./platform-copy";
import { StudioDialogs } from "./dialogs";
import { VideoProgress } from "./video-progress";
import { SetupBanner } from "./app-settings";
import {
  canPick,
  defaultQueueAccount,
  PickBox,
  QueueBar,
  queuedFor,
} from "./clip-queue";
import {
  AnalyticsPage,
  ConnectionsPage,
  InsightsPage,
  QueuePage,
  SettingsPage,
  SourcesPage,
} from "./pages";
const nav = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "sources", label: "Sources", icon: Radio },
  { id: "clips", label: "Clip library", icon: Clapperboard },
  { id: "queue", label: "Publishing queue", icon: CalendarClock },
  { id: "analytics", label: "Analytics", icon: BarChart3 },
  { id: "insights", label: "AI insights", icon: Sparkles },
];
const titles: Record<string, [string, string]> = {
  overview: [
    "Your studio, at a glance.",
    "From long-form ideas to your next great short.",
  ],
  sources: [
    "Good content starts here.",
    "The authorized sources that keep your studio moving.",
  ],
  clips: [
    "Find your next great clip.",
    "Every candidate, ranked and ready for a closer look.",
  ],
  queue: [
    "The right clip. The right time.",
    "Your publishing schedule, with room to stay in control.",
  ],
  analytics: [
    "See what resonates.",
    "Measured performance across your content and channels.",
  ],
  insights: [
    "A smarter studio, every day.",
    "Turn measured results into your next creative decision.",
  ],
  connections: [
    "Connect your creative stack.",
    "Your clipping engines, AI models and publishing channels.",
  ],
  settings: [
    "Set the pace.",
    "Put your studio on autopilot, within your limits.",
  ],
};
export type Dialog = {
  type:
    | "source"
    | "video"
    | "account"
    | "setup"
    | "schedule"
    | "metrics"
    | "reconcile"
    | "publication";
  source?: Source;
  clip?: Clip;
  post?: Post;
  projectId?: string;
} | null;
export default function Dashboard({ view }: { view: string }) {
  const [studio, setStudio] = useState<Studio | null>(null),
    [clips, setClips] = useState<Clip[]>([]),
    [total, setTotal] = useState(0),
    [posts, setPosts] = useState<Post[]>([]);
  const [auth, setAuth] = useState<boolean | null>(null),
    [password, setPassword] = useState(""),
    // First run of the desktop app: no password exists yet, so the owner creates one.
    [firstRun, setFirstRun] = useState(false),
    [desktopApp, setDesktopApp] = useState(false),
    [confirmPassword, setConfirmPassword] = useState(""),
    [error, setError] = useState(""),
    [toast, setToast] = useState(""),
    [busy, setBusy] = useState(false);
  const [q, setQ] = useState(""),
    [status, setStatus] = useState("all"),
    [provider, setProvider] = useState("all"),
    [offset, setOffset] = useState(0),
    [grid, setGrid] = useState(true),
    [mobile, setMobile] = useState(false);
  const [dialog, setDialog] = useState<Dialog>(null),
    [selected, setSelected] = useState<Clip | null>(null),
    [flags, setFlags] = useState(false);
  // Clips picked in the library, in pick order, and the channel they'll be queued to.
  const [picked, setPicked] = useState<Clip[]>([]),
    [queueAccount, setQueueAccount] = useState("");
  const closeDialog = useCallback(() => setDialog(null), []),
    closeClip = useCallback(() => setSelected(null), []);
  const refresh = useCallback(async () => {
    try {
      const [s, c, p] = await Promise.all([
        api<Studio>("/studio"),
        api<{ items: Clip[]; total: number }>(
          "/clips?" +
            new URLSearchParams({
              q,
              status,
              provider,
              offset: String(offset),
              limit: "24",
            }),
        ),
        api<Post[]>("/queue"),
      ]);
      setStudio(s);
      setClips(c.items);
      setTotal(c.total);
      setPosts(p);
      setAuth(true);
      setError("");
    } catch (e) {
      const err = e as Error & { status?: number };
      if (err.status === 401) setAuth(false);
      else setError(err.message);
    }
  }, [q, status, provider, offset]);
  useEffect(() => {
    const id = setTimeout(() => {
      void refresh();
    }, 200);
    return () => clearTimeout(id);
  }, [refresh]);
  useEffect(() => {
    if (!auth) return;
    const id = setInterval(() => void refresh(), 15000);
    return () => clearInterval(id);
  }, [auth, refresh]);
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(""), 6000);
    return () => clearTimeout(id);
  }, [toast]);
  useEffect(() => {
    if (auth !== false) return;
    api<{ needs_password: boolean; app_settings: boolean }>("/setup/status")
      .then((s) => {
        setFirstRun(s.needs_password);
        setDesktopApp(s.app_settings);
      })
      .catch(() => setFirstRun(false));
  }, [auth]);
  const perform = async (action: () => Promise<unknown>, message: string) => {
    setBusy(true);
    setError("");
    try {
      await action();
      setToast(message);
      await refresh();
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  };
  const changeSettings = (body: unknown) =>
    perform(() => api("/settings", body, "PATCH"), "Studio settings updated");
  const inspectClip = async (clip: Clip) => {
    setFlags(false);
    setSelected(clip);
    try {
      setSelected(await api<Clip>("/clips/" + clip.id));
    } catch (e) {
      setError((e as Error).message);
    }
  };
  if (auth === false)
    return (
      <main className="login-page">
        <div className="login-visual">
          <div className="login-orbit" />
          <div className="brand">
            <span className="brand-mark">
              <AudioLines size={25} />
            </span>
            clipbot<span className="ai-label">AI</span>
          </div>
          <div className="login-message">
            <span className="eyebrow">YOUR AUTONOMOUS CONTENT STUDIO</span>
            <h1>
              Big ideas.
              <br />A shorter format.
              <br />
              <em>More possibility.</em>
            </h1>
            <p>A home for the moments worth sharing.</p>
          </div>
          <span className="login-foot">
            GENERATE &nbsp; / &nbsp; SELECT &nbsp; / &nbsp; PUBLISH &nbsp; /
            &nbsp; LEARN
          </span>
        </div>
        <form
          className="login-form"
          onSubmit={async (e) => {
            e.preventDefault();
            if (firstRun && password !== confirmPassword) {
              setError("The two passwords don't match.");
              return;
            }
            const done = await perform(
              () =>
                api(firstRun ? "/setup/password" : "/auth/login", { password }),
              firstRun
                ? "Your studio is ready. Next, add your keys in Connections."
                : "Welcome to your studio",
            );
            if (done && firstRun) window.location.href = "/connections";
          }}
        >
          <div className="login-icon">
            <WandSparkles size={28} />
          </div>
          <h2>{firstRun ? "Welcome to ClipBot." : "Welcome to your studio."}</h2>
          <p>
            {firstRun
              ? "Create a password for your studio. You'll use it to open the dashboard."
              : "Sign in to keep your content moving."}
          </p>
          <label>
            {firstRun ? "New studio password" : "Studio password"}
            <input
              autoFocus
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={firstRun ? 8 : undefined}
              autoComplete={firstRun ? "new-password" : "current-password"}
              placeholder={
                firstRun ? "At least 8 characters" : "Enter your password"
              }
            />
          </label>
          {firstRun && (
            <label>
              Type it again
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                autoComplete="new-password"
              />
            </label>
          )}
          {error && (
            <div className="inline-error" role="alert">
              {error}
            </div>
          )}
          <button className="button primary" disabled={busy}>
            {busy ? (
              <Loader2 className="spin" size={18} />
            ) : (
              <>
                {firstRun ? "Create password" : "Open studio"}{" "}
                <ArrowRight size={17} />
              </>
            )}
          </button>
          <small>
            {desktopApp
              ? "Forgot it? Right-click the ClipBot icon in the taskbar tray and choose Reset studio password."
              : "Use the ADMIN_PASSWORD configured in your .env file."}
          </small>
        </form>
      </main>
    );
  if (!studio)
    return (
      <main className="loading">
        <AudioLines size={32} />
        <h2>Opening your studio…</h2>
        {error ? (
          <>
            <p role="alert">{error}</p>
            <button className="button" onClick={() => void refresh()}>
              Retry connection
            </button>
          </>
        ) : (
          <Loader2 size={20} className="spin" />
        )}
      </main>
    );
  const settings = studio.settings,
    active = settings.autopilot && !settings.stop_all_posting;
  const heartbeat =
    !!settings.last_heartbeat &&
    Date.now() - new Date(settings.last_heartbeat).getTime() < 120000;
  const upcoming = posts
    .filter((p) => p.status === "scheduled")
    .sort((a, b) => a.scheduled_at.localeCompare(b.scheduled_at));
  const reviewJobs = studio.jobs.filter((j) =>
    ["blocked", "dead_letter", "needs_reconciliation"].includes(j.status),
  );
  const approved =
    (studio.counts.approved || 0) +
    (studio.counts.scheduled || 0) +
    (studio.counts.published || 0);
  const totalSpend = studio.usage.reduce((n, v) => n + v.cost, 0);
  const pickAccount = queueAccount || defaultQueueAccount(studio);
  const queued = queuedFor(posts, pickAccount);
  const togglePick = (clip: Clip) => {
    const entry = queued.get(clip.id);
    if (entry) {
      void perform(
        () => api("/queue/" + entry.post.id + "/cancel?compact=true", {}),
        `Took “${clip.title}” out of the queue; the clips after it moved up.`,
      );
      return;
    }
    setPicked(
      picked.some((c) => c.id === clip.id)
        ? picked.filter((c) => c.id !== clip.id)
        : [...picked, clip],
    );
  };
  return (
    <div className="app-shell">
      <aside className={"sidebar " + (mobile ? "open" : "")}>
        <Link href="/" className="brand">
          <span className="brand-mark">
            <AudioLines size={25} />
          </span>
          clipbot<span className="ai-label">AI</span>
        </Link>
        <button
          className="workspace-switch"
          onClick={() => setDialog({ type: "setup" })}
        >
          <span className="workspace-avatar">B</span>
          <span>
            My creator studio<small>Personal workspace</small>
          </span>
          <ChevronDown size={14} />
        </button>
        <span className="nav-caption">WORKSPACE</span>
        <nav>
          {nav.map((n) => (
            <Link
              key={n.id}
              onClick={() => setMobile(false)}
              href={n.id === "overview" ? "/" : "/" + n.id}
              className={"nav-item " + (view === n.id ? "selected" : "")}
            >
              <n.icon size={18} />
              {n.label}
              {n.id === "queue" && upcoming.length > 0 && (
                <span className="nav-count">{upcoming.length}</span>
              )}
            </Link>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="autopilot-card">
            <div>
              <Zap size={16} />
              <span>Made for momentum</span>
            </div>
            <p>One source. More great moments. Your studio does the rest.</p>
            <button onClick={() => setDialog({ type: "setup" })}>
              Studio setup <ArrowUpRight size={15} />
            </button>
          </div>
          <Link
            className={"nav-item " + (view === "connections" ? "selected" : "")}
            href="/connections"
          >
            <Layers size={18} />
            Connections
          </Link>
          <Link
            className={"nav-item " + (view === "settings" ? "selected" : "")}
            href="/settings"
          >
            <Settings2 size={18} />
            Settings
          </Link>
          <div className="owner">
            <span className="owner-avatar">AV</span>
            <span>
              Studio owner<small>Personal workspace</small>
            </span>
            <button
              className="icon-button"
              aria-label="Sign out"
              onClick={() =>
                void perform(() => api("/auth/logout", {}), "Signed out")
              }
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumbs">
            <button
              className="mobile-menu icon-button"
              aria-label="Toggle navigation"
              onClick={() => setMobile(!mobile)}
            >
              <Menu size={20} />
            </button>
            <span>Workspace</span>
            <ChevronRight size={12} />
            <strong>
              {view === "clips"
                ? "Clip library"
                : view[0].toUpperCase() + view.slice(1)}
            </strong>
          </div>
          <div className="topbar-right">
            <span className="live-indicator">
              <i className={heartbeat ? "" : "muted-dot"} />
              {heartbeat ? "Worker online" : "Worker not detected"}
            </span>
            <button
              className="icon-button notification"
              aria-label="View jobs needing attention"
              onClick={() => {
                window.location.href = "/queue";
              }}
            >
              <Bell size={17} />
              {reviewJobs.length > 0 && <i />}
            </button>
            <span className="small-avatar">AV</span>
          </div>
        </header>
        <main className="main-content">
          {studio.demo_mode && (
            <div className="demo-banner">
              <span>
                <Sparkles size={14} />
                Development workspace · Clips and performance marked as samples
                are simulated.
              </span>
              <button
                disabled={busy}
                onClick={() =>
                  void perform(
                    () => api("/demo/seed", {}),
                    "Development data loaded; the worker will process the new episode",
                  )
                }
              >
                {studio.sources.some((s) => s.demo)
                  ? "Reload samples"
                  : "Load sample workflow"}
                <ArrowRight size={13} />
              </button>
            </div>
          )}
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                {view === "overview"
                  ? "A LITTLE LESS WORK. A LOT MORE CONTENT."
                  : "YOUR CREATOR STUDIO"}
              </div>
              <h1>{titles[view][0]}</h1>
              <p>{titles[view][1]}</p>
            </div>
            <div className="heading-actions">
              {view === "overview" && (
                <button
                  className={"autopilot-pill " + (active ? "on" : "")}
                  onClick={() =>
                    void changeSettings({ autopilot: !settings.autopilot })
                  }
                >
                  <i />
                  {active ? "Autopilot on" : "Autopilot paused"}
                  <ChevronDown size={13} />
                </button>
              )}
              <button
                className="button primary"
                disabled={busy}
                onClick={() =>
                  setDialog({ type: view === "sources" ? "source" : "video" })
                }
              >
                <Plus size={17} />
                {view === "sources" ? "Add source" : "Add video"}
              </button>
            </div>
          </div>
          {error && (
            <div className="error-banner" role="alert">
              {error}
              <button
                className="icon-button"
                aria-label="Dismiss error"
                onClick={() => setError("")}
              >
                <X size={16} />
              </button>
            </div>
          )}
          <VideoProgress
            videos={studio.recent_videos}
            showFinished={view === "overview" || view === "clips"}
            onConfirm={(projectId, externalId) =>
              perform(
                () =>
                  api("/projects/" + projectId + "/reconcile", {
                    external_id: externalId,
                    completion_confirmed: true,
                  }),
                "Importing the clips. The card shows when they’re ready to review.",
              )
            }
          />
          {view === "overview" && (
            <>
              <SetupBanner studio={studio} />
              <div className="stats-grid">
                <Stat
                  label="Source videos"
                  value={number(studio.counts.videos)}
                  detail={studio.counts.sources + " authorized sources"}
                  icon={Film}
                />
                <Stat
                  label="Clips generated"
                  value={number(studio.counts.clips)}
                  detail={
                    approved +
                    " selected · " +
                    (studio.counts.rejected || 0) +
                    " rejected"
                  }
                  icon={Clapperboard}
                />
                <Stat
                  label="Clips published"
                  value={number(studio.counts.published || 0)}
                  detail={upcoming.length + " posts in the queue"}
                  icon={Upload}
                />
                <Stat
                  label="Views · last 7 days"
                  value={number(studio.analytics.views_7d)}
                  detail={
                    studio.analytics.followers_available
                      ? number(studio.analytics.followers_gained) +
                        " followers gained"
                      : "Follower metrics not available yet"
                  }
                  icon={BarChart3}
                />
              </div>
              <div className="pipeline-strip">
                <div className="pipeline-intro">
                  <span className="pulse-icon">
                    <Activity size={18} />
                  </span>
                  <span>
                    Content pipeline
                    <small>
                      {heartbeat
                        ? "Your studio is working"
                        : "Waiting for the worker"}
                    </small>
                  </span>
                </div>
                {[
                  { name: "Detected", n: studio.counts.videos, url: "sources" },
                  { name: "Generated", n: studio.counts.clips, url: "clips" },
                  { name: "Selected", n: approved, url: "clips" },
                  { name: "Scheduled", n: upcoming.length, url: "queue" },
                  {
                    name: "Published",
                    n: studio.counts.published || 0,
                    url: "analytics",
                  },
                ].map((step, i) => (
                  <div className="pipeline-step" key={step.name}>
                    {i > 0 && <ChevronRight size={13} />}
                    <Link href={"/" + step.url}>
                      <b>{number(step.n)}</b>
                      <span>{step.name}</span>
                    </Link>
                  </div>
                ))}
              </div>
              <div className="overview-middle">
                <section className="panel reach-panel">
                  <div className="panel-heading">
                    <div>
                      <h2>Every view starts with a moment.</h2>
                      <p>Observed reach across your channels</p>
                    </div>
                    <span className="period">
                      Last 7 days <ChevronDown size={12} />
                    </span>
                  </div>
                  <div className="reach-total">
                    {number(studio.analytics.views_7d)}
                    <span>
                      <i />
                      Observed views
                    </span>
                  </div>
                  <ReachChart data={studio.analytics.trend} />
                  <div className="chart-foot">
                    <span>
                      <i className="legend-dot" />
                      All platforms
                    </span>
                    <span>
                      {studio.demo_mode
                        ? "Simulated development analytics"
                        : "Based on recorded analytics snapshots"}
                    </span>
                  </div>
                </section>
                <section className="panel engines-panel">
                  <div className="panel-heading">
                    <div>
                      <h2>Two engines. One winner.</h2>
                      <p>Compare your clipping performance</p>
                    </div>
                    <Zap size={18} className="lime" />
                  </div>
                  {["vizard", "opus"].map((name) => {
                    const metric = studio.analytics.breakdown.find(
                      (b) => b.dimension === "provider" && b.label === name,
                    );
                    return (
                      <div key={name} className={"engine-result " + name}>
                        <div className="engine-name">
                          <span className={"engine-logo " + name}>
                            {name === "vizard" ? (
                              <WandSparkles size={18} />
                            ) : (
                              <AudioLines size={19} />
                            )}
                          </span>
                          <div>
                            <b>{name === "vizard" ? "Vizard" : "OpusClip"}</b>
                            <small>
                              {metric?.published || 0} measured publications
                            </small>
                          </div>
                        </div>
                        <strong>
                          {metric ? number(metric.median_views) : "—"}
                          <small>median views</small>
                        </strong>
                        <div className="engine-meter">
                          <i
                            style={{
                              width: metric
                                ? Math.min(
                                    100,
                                    (metric.median_views /
                                      Math.max(
                                        ...studio.analytics.breakdown
                                          .filter(
                                            (b) => b.dimension === "provider",
                                          )
                                          .map((b) => b.median_views),
                                        1,
                                      )) *
                                      100,
                                  ) + "%"
                                : "0%",
                            }}
                          />
                        </div>
                      </div>
                    );
                  })}
                  <div className="engine-note">
                    <Sparkles size={15} />
                    <span>
                      {studio.demo_mode
                        ? "Sample results illustrate the comparison. Live routing learns from real 24-hour cohorts."
                        : "Routing adapts after enough comparable publications are measured."}
                    </span>
                  </div>
                  <Link className="text-link" href="/analytics">
                    Explore engine performance <ArrowUpRight size={14} />
                  </Link>
                </section>
              </div>
              <div className="overview-bottom">
                <section>
                  <div className="section-heading">
                    <div>
                      <h2>Moments worth sharing</h2>
                      <p>Your highest-ranked clips</p>
                    </div>
                    <Link className="text-link" href="/clips">
                      View library <ArrowRight size={14} />
                    </Link>
                  </div>
                  {clips.length ? (
                    <div className="featured-clips">
                      {clips.slice(0, 3).map((c) => (
                        <ClipCard
                          key={c.id}
                          clip={c}
                          onClick={() => void inspectClip(c)}
                          compact
                        />
                      ))}
                    </div>
                  ) : (
                    <div className="panel">
                      <Empty
                        title="Your next great moment starts here"
                        text="Add an authorized source, then submit a video to start both clipping engines."
                        action={
                          <button
                            className="button"
                            onClick={() => setDialog({ type: "setup" })}
                          >
                            Set up your studio <ArrowRight size={15} />
                          </button>
                        }
                      />
                    </div>
                  )}
                </section>
                <section className="panel upcoming-panel">
                  <div className="panel-heading">
                    <div>
                      <h2>Next in line</h2>
                      <p>{settings.timezone}</p>
                    </div>
                    <CalendarClock size={18} />
                  </div>
                  {upcoming.slice(0, 3).map((p) => (
                    <div className="upcoming-post" key={p.id}>
                      <span className={"platform-icon " + p.platform}>
                        {p.platform === "youtube" ? (
                          <Play size={14} />
                        ) : p.platform === "instagram" ? (
                          <Square size={14} />
                        ) : (
                          <AudioLines size={14} />
                        )}
                      </span>
                      <div>
                        <h4>{p.title}</h4>
                        <p>{date(p.scheduled_at, settings.timezone)}</p>
                      </div>
                    </div>
                  ))}
                  {!upcoming.length && (
                    <div className="queue-empty">
                      <CalendarClock size={27} />
                      <p>Your queue is open.</p>
                      <small>
                        Approved clips will appear here once scheduled.
                      </small>
                    </div>
                  )}
                  <Link className="text-link" href="/queue">
                    Open publishing queue <ArrowRight size={14} />
                  </Link>
                  <div className="mini-cost">
                    <span>Today’s reserved cost</span>
                    <b>${totalSpend.toFixed(2)}</b>
                  </div>
                </section>
              </div>
            </>
          )}
          {view === "sources" && (
            <SourcesPage
              studio={studio}
              busy={busy}
              perform={perform}
              onEdit={(source) => setDialog({ type: "source", source })}
              onAdd={() => setDialog({ type: "source" })}
            />
          )}
          {view === "clips" && (
            <>
              <BulkActions
                studio={studio}
                provider={provider}
                query={q}
                refresh={refresh}
              />
              <QueueBar
                studio={studio}
                queued={queued}
                picked={picked}
                setPicked={setPicked}
                account={pickAccount}
                setAccount={(id) => {
                  setQueueAccount(id);
                  setPicked([]);
                }}
                refresh={refresh}
              />
              <div className="clip-toolbar">
                <div className="search-input">
                  <Search size={16} />
                  <input
                    placeholder="Search titles or topics…"
                    aria-label="Search clips"
                    value={q}
                    onChange={(e) => {
                      setQ(e.target.value);
                      setOffset(0);
                    }}
                  />
                </div>
                <select
                  aria-label="Filter clipping engine"
                  value={provider}
                  onChange={(e) => {
                    setProvider(e.target.value);
                    setOffset(0);
                  }}
                >
                  <option value="all">All engines</option>
                  <option value="vizard">Vizard</option>
                  <option value="opus">OpusClip</option>
                </select>
                <button
                  className="icon-button"
                  aria-label="Toggle grid or list"
                  onClick={() => setGrid(!grid)}
                >
                  {grid ? <Layers size={18} /> : <LayoutDashboard size={18} />}
                </button>
              </div>
              <div className="filter-chips">
                {[
                  "all",
                  "candidate",
                  "analyzing",
                  "approved",
                  "reserve",
                  "scheduled",
                  "published",
                  "rejected",
                  "failed",
                ].map((s) => (
                  <button
                    key={s}
                    className={s === status ? "active" : ""}
                    onClick={() => {
                      setStatus(s);
                      setOffset(0);
                    }}
                  >
                    {s === "all" ? "All clips" : s}
                  </button>
                ))}
                <span>{total} clips</span>
              </div>
              {clips.length ? (
                <div className={grid ? "clip-grid" : "clip-grid list-mode"}>
                  {clips.map((c) => {
                    const entry = queued.get(c.id);
                    const at = picked.findIndex((p) => p.id === c.id);
                    const n = entry
                      ? entry.n
                      : at >= 0
                        ? queued.size + at + 1
                        : 0;
                    return (
                      <div
                        key={c.id}
                        className={"clip-pick" + (n ? " on" : "")}
                      >
                        <ClipCard clip={c} onClick={() => void inspectClip(c)} />
                        {(entry || canPick(c, studio.demo_mode)) && (
                          <PickBox
                            n={n}
                            title={c.title}
                            queuedAt={
                              entry
                                ? date(entry.post.scheduled_at, settings.timezone)
                                : null
                            }
                            onToggle={() => togglePick(c)}
                          />
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <Empty
                  title="No clips in this view"
                  text="Try another filter, or add a video to generate your first candidates."
                />
              )}
              <div className="pagination">
                <span>
                  {total ? offset + 1 : 0}–{Math.min(offset + 24, total)} of{" "}
                  {total}
                </span>
                <button
                  className="button"
                  disabled={offset === 0}
                  onClick={() => setOffset(offset - 24)}
                >
                  <ChevronLeft size={15} />
                  Previous
                </button>
                <button
                  className="button"
                  disabled={offset + 24 >= total}
                  onClick={() => setOffset(offset + 24)}
                >
                  Next
                  <ChevronRight size={15} />
                </button>
              </div>
            </>
          )}
          {view === "queue" && (
            <QueuePage
              studio={studio}
              posts={posts}
              perform={perform}
              onPublication={(post) => setDialog({ type: "publication", post })}
              onMetrics={(post) => setDialog({ type: "metrics", post })}
              onReconcile={(projectId) =>
                setDialog({ type: "reconcile", projectId })
              }
            />
          )}
          {view === "analytics" && <AnalyticsPage studio={studio} />}
          {view === "insights" && <InsightsPage studio={studio} />}
          {view === "connections" && (
            <ConnectionsPage
              studio={studio}
              onAccount={() => setDialog({ type: "account" })}
              onSetup={() => setDialog({ type: "setup" })}
              perform={perform}
              busy={busy}
            />
          )}
          {view === "settings" && (
            <SettingsPage studio={studio} perform={perform} busy={busy} />
          )}
          <footer className="workspace-footer">
            <span>
              <ShieldCheck size={13} />
              Your content. Your channels. Your control.
            </span>
            <span>
              ClipBot Studio <i />
              v0.1
            </span>
          </footer>
        </main>
      </div>
      {toast && (
        <div className="toast" role="status">
          <Check size={17} />
          {toast}
        </div>
      )}
      <StudioDialogs
        key={dialog?.type || "closed"}
        error={error}
        dialog={dialog}
        close={closeDialog}
        studio={studio}
        busy={busy}
        perform={perform}
      />
      {selected && (
        <Modal
          title="A closer look"
          subtitle={
            selected.provider === "opus"
              ? "Generated by OpusClip"
              : "Generated by Vizard"
          }
          onClose={closeClip}
        >
          <div className="review-layout">
            <div>
              {selected.storage_key ? (
                <video
                  className="review-video"
                  src={"/api/clips/" + selected.id + "/media"}
                  controls
                />
              ) : (
                <div className="review-no-video">
                  <Film size={40} />
                  <h3>
                    {selected.demo ? "Development sample" : "Media pending"}
                  </h3>
                  <p>
                    {selected.demo
                      ? "This fixture demonstrates the workflow. It contains no video."
                      : "The worker will archive the provider’s video before approval."}
                  </p>
                </div>
              )}
              <div className="review-summary">
                <Badge kind={selected.status}>{selected.status}</Badge>
                <strong>
                  {number(selected.overall_score)}
                  <small>/100</small>
                </strong>
              </div>
              {selected.storage_key && (
                <a
                  className="button wide"
                  href={"/api/clips/" + selected.id + "/media"}
                  download
                >
                  <ArrowDownToLine size={16} />
                  Download clip
                </a>
              )}
            </div>
            <div className="review-content">
              <h3>{selected.title}</h3>
              <p className="muted">
                {selected.topic} · {Math.round(selected.duration)} seconds
              </p>
              <h4>Why this clip</h4>
              <p>{selected.reason}</p>
              {selected.evaluation?.scores && (
                <div className="rubric-bars">
                  {Object.entries(selected.evaluation.scores).map(
                    ([key, v]) => (
                      <div key={key}>
                        <span>{key}</span>
                        <div>
                          <i style={{ width: v + "%" }} />
                        </div>
                        <b>{v}</b>
                      </div>
                    ),
                  )}
                </div>
              )}
              <details open>
                <summary>Transcript</summary>
                <p className="transcript">{selected.transcript}</p>
              </details>
              <details>
                <summary>Platform copy & hooks</summary>
                <PlatformCopy metadata={selected.metadata_json} />
              </details>
              {selected.policy_flags.length > 0 && (
                <div className="flag-review">
                  <Badge kind="reserve">Review needed</Badge>
                  <p>{selected.policy_flags.join(", ")}</p>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={flags}
                      onChange={(e) => setFlags(e.target.checked)}
                    />
                    I have reviewed these flags and approve this content.
                  </label>
                </div>
              )}
              {error && (
                <p className="inline-error" role="alert">
                  {error}
                </p>
              )}
              <div className="review-actions">
                {!["scheduled", "publishing", "published"].includes(
                  selected.status,
                ) && (
                  <>
                    <button
                      className="button danger-subtle"
                      disabled={busy}
                      onClick={async () => {
                        if (
                          await perform(
                            () =>
                              api("/clips/" + selected.id + "/review", {
                                action: "reject",
                              }),
                            "Clip rejected",
                          )
                        )
                          closeClip();
                      }}
                    >
                      Reject
                    </button>
                    <button
                      className="button primary"
                      disabled={busy || !!selected.duplicate_of}
                      onClick={async () => {
                        if (
                          await perform(
                            () =>
                              api("/clips/" + selected.id + "/review", {
                                action: "approve",
                                acknowledge_flags: flags,
                              }),
                            "Clip approved",
                          )
                        )
                          closeClip();
                      }}
                    >
                      <Check size={16} />
                      Approve clip
                    </button>
                  </>
                )}
                {["approved", "scheduled", "published"].includes(
                  selected.status,
                ) && (
                  <button
                    className="button primary"
                    onClick={() => {
                      setDialog({ type: "schedule", clip: selected });
                      closeClip();
                    }}
                  >
                    <CalendarClock size={16} />
                    Schedule
                  </button>
                )}
              </div>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
