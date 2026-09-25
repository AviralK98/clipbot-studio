"use client";
import { useState } from "react";
import Link from "next/link";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  AudioLines,
  CalendarClock,
  Check,
  ChevronDown,
  CircleHelp,
  Edit3,
  ExternalLink,
  FileText,
  Layers,
  Pause,
  Play,
  Plus,
  Radio,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Sparkles,
  Square,
  Trash2,
  TriangleAlert,
  Zap,
} from "lucide-react";
import { api, date, number, Post, Source, Studio } from "@/lib/types";
import { Badge, Empty, ReachChart, Toggle } from "./ui";
import { VideoInsights } from "./video-insights";
export type Perform = (
  action: () => Promise<unknown>,
  message: string,
) => Promise<boolean>;
export function SourcesPage({
  studio,
  busy,
  perform,
  onEdit,
  onAdd,
}: {
  studio: Studio;
  busy: boolean;
  perform: Perform;
  onEdit: (s: Source) => void;
  onAdd: () => void;
}) {
  return (
    <>
      <div className="section-heading">
        <div>
          <h2>
            Your source collection{" "}
            <span className="count-pill">{studio.sources.length}</span>
          </h2>
          <p>
            Authorization travels with every clip, all the way to publication.
          </p>
        </div>
        <Badge kind="approved">
          <ShieldCheck size={12} />
          Rights recorded
        </Badge>
      </div>
      {!studio.sources.length ? (
        <div className="panel">
          <Empty
            title="Start with a source you own"
            text="Add a channel, playlist, video feed or local folder. Record where you have permission to publish."
            action={
              <button className="button primary" onClick={onAdd}>
                <Plus size={16} />
                Add your first source
              </button>
            }
          />
        </div>
      ) : (
        <div className="source-grid">
          {studio.sources.map((s) => (
            <article key={s.id} className="panel source-card">
              <div className="source-top">
                <span className="source-icon">
                  <Radio size={24} />
                </span>
                <Toggle
                  checked={s.enabled}
                  label={"Enable " + s.name}
                  onChange={() => {
                    const { id, demo, last_checked_at, last_error, ...input } =
                      s;
                    void perform(
                      () =>
                        api(
                          "/sources/" + id,
                          { ...input, enabled: !s.enabled },
                          "PUT",
                        ),
                      "Source updated",
                    );
                  }}
                />
              </div>
              <div>
                <h3>{s.name}</h3>
                <p className="source-url">{s.url}</p>
              </div>
              <div className="source-tags">
                <Badge kind={s.enabled ? "approved" : "neutral"}>
                  {s.enabled ? "Monitoring enabled" : "Paused"}
                </Badge>
                <Badge>{s.kind.replaceAll("_", " ")}</Badge>
                {s.demo && <Badge kind="reserve">Sample</Badge>}
              </div>
              <div className="source-detail">
                <span>Clipping engine</span>
                <b>{s.routing === "dual" ? "Vizard + OpusClip" : s.routing}</b>
              </div>
              <div className="source-detail">
                <span>Publishing rights</span>
                <b>{s.authorized_platforms.join(" · ")}</b>
              </div>
              <div className="source-detail">
                <span>Authorization</span>
                <b>{s.authorization_type}</b>
              </div>
              <p className="source-note">{s.authorization_note}</p>
              {s.last_error && (
                <div className="inline-error">{s.last_error}</div>
              )}
              <div className="source-actions">
                <span>
                  {s.last_checked_at
                    ? "Checked " + date(s.last_checked_at)
                    : "Awaiting first scan"}
                </span>
                <button
                  className="icon-button"
                  disabled={busy || s.kind === "manual"}
                  aria-label={"Scan " + s.name}
                  onClick={() =>
                    void perform(
                      () => api("/sources/" + s.id + "/scan", {}),
                      "Source scan queued",
                    )
                  }
                >
                  <RefreshCw size={16} />
                </button>
                <button
                  className="icon-button"
                  aria-label={"Edit " + s.name}
                  onClick={() => onEdit(s)}
                >
                  <Edit3 size={16} />
                </button>
                <button
                  className="icon-button"
                  aria-label={"Archive " + s.name}
                  onClick={() =>
                    void perform(
                      () => api("/sources/" + s.id, undefined, "DELETE"),
                      "Source archived; authorization history retained",
                    )
                  }
                >
                  <Trash2 size={16} />
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
      <div className="info-note">
        <CircleHelp size={17} />
        <span>
          YouTube monitoring uses the official Data API. RSS needs video
          enclosures and duration metadata. Drive and Dropbox videos can be
          submitted as authorized URLs; folder OAuth connectors are not enabled.
        </span>
      </div>
    </>
  );
}
export function QueuePage({
  studio,
  posts,
  perform,
  onMetrics,
  onReconcile,
  onPublication,
}: {
  studio: Studio;
  posts: Post[];
  perform: Perform;
  onMetrics: (p: Post) => void;
  onReconcile: (id: string) => void;
  onPublication: (p: Post) => void;
}) {
  const [filter, setFilter] = useState("all");
  const visible = posts.filter((p) => filter === "all" || p.status === filter);
  return (
    <>
      <div className="queue-control panel">
        <div>
          <span
            className={
              "pulse-icon " +
              (studio.settings.stop_all_posting ? "stopped" : "")
            }
          >
            <CalendarClock size={20} />
          </span>
          <div>
            <h3>
              {studio.settings.stop_all_posting
                ? "Publishing is stopped"
                : "Your publishing schedule"}
            </h3>
            <p>
              {studio.settings.posting_times.join(" / ")} ·{" "}
              {studio.settings.timezone} · max {studio.settings.daily_limit} per
              platform daily
            </p>
          </div>
        </div>
        <button
          className={
            "button " +
            (studio.settings.stop_all_posting ? "primary" : "danger-subtle")
          }
          onClick={() =>
            void perform(
              () =>
                api(
                  "/settings",
                  { stop_all_posting: !studio.settings.stop_all_posting },
                  "PATCH",
                ),
              studio.settings.stop_all_posting
                ? "Posting resumed"
                : "All new posting attempts stopped",
            )
          }
        >
          {studio.settings.stop_all_posting ? (
            <Play size={15} />
          ) : (
            <Square size={14} />
          )}{" "}
          {studio.settings.stop_all_posting
            ? "Resume posting"
            : "Stop all posting"}
        </button>
      </div>
      <div className="filter-chips">
        {[
          "all",
          "scheduled",
          "publishing",
          "published",
          "failed",
          "needs_reconciliation",
          "cancelled",
        ].map((s) => (
          <button
            key={s}
            className={filter === s ? "active" : ""}
            onClick={() => setFilter(s)}
          >
            {s.replaceAll("_", " ")}
          </button>
        ))}
      </div>
      <div className="panel table-panel">
        {visible.length ? (
          <table>
            <thead>
              <tr>
                <th>Clip</th>
                <th>Channel</th>
                <th>Scheduled for</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {visible.map((p) => (
                <tr key={p.id}>
                  <td>
                    <b>{p.title}</b>
                    {p.error && <small className="error-text">{p.error}</small>}
                    {p.demo && <small>Development sample</small>}
                  </td>
                  <td>
                    <span className={"platform-text " + p.platform}>
                      {p.platform}
                    </span>
                    <small>{p.account}</small>
                  </td>
                  <td>{date(p.scheduled_at, studio.settings.timezone)}</td>
                  <td>
                    <Badge kind={p.status}>
                      {p.status.replaceAll("_", " ")}
                    </Badge>
                  </td>
                  <td>
                    <div className="row-actions">
                      {["needs_reconciliation", "failed"].includes(
                        p.status,
                      ) && (
                        <button
                          className="button small"
                          onClick={() => onPublication(p)}
                        >
                          Record published post
                        </button>
                      )}
                      {p.publication && (
                        <button
                          className="icon-button"
                          aria-label={"Attach analytics for " + p.title}
                          onClick={() => onMetrics(p)}
                        >
                          <Activity size={16} />
                        </button>
                      )}
                      {p.publication?.url && (
                        <a
                          className="icon-button"
                          aria-label="Open published post"
                          href={p.publication.url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          <ExternalLink size={15} />
                        </a>
                      )}
                      {["scheduled", "failed"].includes(p.status) && (
                        <button
                          className="button small"
                          onClick={() =>
                            void perform(
                              () => api("/queue/" + p.id + "/cancel", {}),
                              "Queued post cancelled",
                            )
                          }
                        >
                          Cancel
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty
            title="A little breathing room"
            text="Approved clips are scheduled here. Inspect a clip to choose its channel and posting time."
            action={
              <Link className="button" href="/clips">
                Open clip library <ArrowRight size={15} />
              </Link>
            }
          />
        )}
      </div>
      <div className="section-heading section-spaced">
        <div>
          <h2>Behind the scenes</h2>
          <p>Durable jobs, retries and anything that needs your attention.</p>
        </div>
        <Badge>
          {studio.jobs.filter((j) => j.status === "running").length} running
        </Badge>
      </div>
      <div className="panel jobs-panel">
        {studio.jobs.length ? (
          studio.jobs.slice(0, 20).map((j) => (
            <div className="job-row" key={j.id}>
              <span className="job-icon">
                <Layers size={16} />
              </span>
              <div>
                <b>{j.kind.replaceAll("_", " ")}</b>
                <p>
                  {j.error ||
                    "Job " + j.id.slice(0, 8) + " · " + date(j.created_at)}
                </p>
              </div>
              <Badge kind={j.status}>{j.status.replaceAll("_", " ")}</Badge>
              {["blocked", "retry", "dead_letter"].includes(j.status) && (
                <button
                  className="icon-button"
                  aria-label={"Retry " + j.kind + " job"}
                  onClick={() =>
                    void perform(
                      () => api("/jobs/" + j.id + "/retry", {}),
                      "Job queued for retry",
                    )
                  }
                >
                  <RefreshCw size={15} />
                </button>
              )}
              {j.status === "needs_reconciliation" && j.payload.project_id && (
                <button
                  className="button small"
                  onClick={() => onReconcile(j.payload.project_id)}
                >
                  Reconcile
                </button>
              )}
            </div>
          ))
        ) : (
          <Empty
            title="No jobs yet"
            text="Add a video and its progress will appear here."
          />
        )}
      </div>
      {studio.projects
        .filter((p) => p.provider === "opus" && p.status === "processing")
        .map((p) => (
          <div className="info-note" key={p.id}>
            <CircleHelp size={17} />
            <span>
              Opus project {p.external_id}: waiting for a signed completion
              callback.
            </span>
            <button className="button small" onClick={() => onReconcile(p.id)}>
              Confirm completed project
            </button>
          </div>
        ))}
    </>
  );
}
export function AnalyticsPage({ studio }: { studio: Studio }) {
  const [dimension, setDimension] = useState("provider");
  const metrics = studio.analytics.breakdown.filter(
    (b) => b.dimension === dimension,
  );
  return (
    <>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Reach over time</h2>
            <p>{studio.analytics.note}</p>
          </div>
          <Badge>{studio.analytics.snapshots} snapshots</Badge>
        </div>
        <div className="analytics-total">
          {number(studio.analytics.views_7d)}
          <span>observed views · 7 days</span>
        </div>
        <ReachChart data={studio.analytics.trend} />
      </section>
      <div className="section-heading section-spaced">
        <div>
          <h2>What’s working</h2>
          <p>
            Latest snapshots per publication. Missing metrics stay unavailable.
          </p>
        </div>
      </div>
      <div className="filter-chips">
        {[
          "provider",
          "topic",
          "platform",
          "duration",
          "hook",
          "posting_time",
        ].map((d) => (
          <button
            className={dimension === d ? "active" : ""}
            onClick={() => setDimension(d)}
            key={d}
          >
            {d.replaceAll("_", " ")}
          </button>
        ))}
      </div>
      <div className="panel table-panel">
        {metrics.length ? (
          <table>
            <thead>
              <tr>
                <th>{dimension.replaceAll("_", " ")}</th>
                <th>Measured posts</th>
                <th>Median views</th>
                <th>Avg watch %</th>
                <th>Shares / 1k</th>
                <th>Followers / 1k</th>
              </tr>
            </thead>
            <tbody>
              {metrics.map((m) => (
                <tr key={m.label}>
                  <td>
                    <b>{m.label}</b>
                  </td>
                  <td>{m.published}</td>
                  <td className="numeric lime">{number(m.median_views)}</td>
                  <td>
                    {m.watch_completion == null
                      ? "—"
                      : m.watch_completion.toFixed(1) + "%"}
                  </td>
                  <td>{number(m.shares_per_1000)}</td>
                  <td>{number(m.followers_per_1000)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty
            title="Your audience will write this part"
            text="Publish a clip and collect a performance snapshot to see the first comparison."
          />
        )}
      </div>
      <div className="insight-explainer">
        <div>
          <ClockIcon />
          <h3>Measured at meaningful moments</h3>
          <p>1 hour · 6 hours · 24 hours · 72 hours · 7 days</p>
        </div>
        <div>
          <ShieldCheck size={20} />
          <h3>Real evidence, visible limits</h3>
          <p>
            Owner analytics depend on platform permissions and reporting delays.
            Manually attached metrics are excluded from automatic learning.
          </p>
        </div>
      </div>
    </>
  );
}
function ClockIcon() {
  return <CalendarClock size={20} />;
}
export function InsightsPage({ studio }: { studio: Studio }) {
  return (
    <>
      <div className="insights-hero panel">
        <span className="insights-symbol">
          <Sparkles size={30} />
        </span>
        <div>
          <Badge kind="approved">THE FEEDBACK LOOP</Badge>
          <h2>Every post is a chance to learn.</h2>
          <p>
            Compare results at 24 hours. Find repeatable patterns. Gradually
            tune your next batch.
          </p>
        </div>
        <div className="feedback-cycle">
          Generate <ArrowRight size={13} /> Select <ArrowRight size={13} />{" "}
          Publish <ArrowRight size={13} /> Learn
        </div>
      </div>
      <VideoInsights />
      {studio.insights.length ? (
        <div className="insight-grid">
          {studio.insights.map((i) => (
            <article className="panel insight-card" key={i.id}>
              <Sparkles size={20} />
              <h3>{i.title}</h3>
              <p>{i.body}</p>
              <Badge>Measured insight</Badge>
            </article>
          ))}
        </div>
      ) : (
        <div className="panel section-spaced">
          <Empty
            title="Good insights take a little evidence"
            text="Automatic recommendations start after at least five comparable real publications per group. Development samples never influence your live strategy."
          />
        </div>
      )}
      <div className="section-heading section-spaced">
        <div>
          <h2>Strategy signals</h2>
          <p>
            Conservative adjustments retain exploration and avoid chasing one
            outlier.
          </p>
        </div>
      </div>
      <div className="panel table-panel">
        {studio.strategy.length ? (
          <table>
            <thead>
              <tr>
                <th>Dimension</th>
                <th>Signal</th>
                <th>Sample size</th>
                <th>24h median views</th>
                <th>Weight</th>
              </tr>
            </thead>
            <tbody>
              {studio.strategy.map((m) => (
                <tr key={m.id}>
                  <td>{m.dimension}</td>
                  <td>
                    <b>{m.label}</b>
                  </td>
                  <td>{m.samples}</td>
                  <td>{number(m.median_views)}</td>
                  <td>
                    <Badge kind={m.weight > 1 ? "approved" : "neutral"}>
                      {m.weight.toFixed(2)}×
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="table-placeholder">
            Your strategy starts neutral. No conclusions without data.
          </p>
        )}
      </div>
    </>
  );
}
export function ConnectionsPage({
  studio,
  onAccount,
  onSetup,
  perform,
}: {
  studio: Studio;
  onAccount: () => void;
  onSetup: () => void;
  perform: Perform;
}) {
  return (
    <>
      <div className="connection-grid">
        {studio.integrations.map((i) => (
          <article className="panel connection-card" key={i.id}>
            <div>
              <span className={"connection-logo " + i.id}>
                {i.id === "opus" ? (
                  <AudioLines size={25} />
                ) : i.id === "ai" ? (
                  <Sparkles size={25} />
                ) : i.id === "youtube" ? (
                  <Play size={25} />
                ) : i.id === "instagram" ? (
                  <Square size={25} />
                ) : (
                  <Zap size={25} />
                )}
              </span>
              <Badge kind={i.configured ? "approved" : "neutral"}>
                {i.configured ? "Configured" : "Setup required"}
              </Badge>
            </div>
            <h3>
              {i.id === "ai"
                ? "Clip review"
                : i.id === "opus"
                  ? "OpusClip"
                  : i.id[0].toUpperCase() + i.id.slice(1)}
            </h3>
            <p>{i.detail}</p>
            <div className="env-variables">
              {i.variables.map((v) => (
                <code key={v}>{v}</code>
              ))}
            </div>
            <button className="text-link" onClick={onSetup}>
              {i.id === "tiktok"
                ? "View publishing limitations"
                : "View setup steps"}
              <ArrowUpRight size={14} />
            </button>
          </article>
        ))}
      </div>
      <div className="section-heading section-spaced">
        <div>
          <h2>Publishing destinations</h2>
          <p>Register a channel after configuring its credentials in .env.</p>
        </div>
        <button className="button" onClick={onAccount}>
          <Plus size={16} />
          Add destination
        </button>
      </div>
      <div className="panel">
        {studio.accounts.length ? (
          studio.accounts.map((a) => (
            <div className="account-row" key={a.id}>
              <span className={"platform-icon " + a.platform}>
                {a.platform === "youtube" ? (
                  <Play size={18} />
                ) : (
                  <Radio size={18} />
                )}
              </span>
              <div>
                <b>{a.name}</b>
                <p>
                  {a.platform} · {a.daily_limit} posts/day
                  {a.demo ? " · Development sample" : ""}
                </p>
              </div>
              <Toggle
                checked={a.enabled}
                label={"Enable " + a.name}
                onChange={() =>
                  void perform(
                    () => api("/accounts/" + a.id + "/toggle", {}),
                    "Destination updated",
                  )
                }
              />
            </div>
          ))
        ) : (
          <Empty
            title="Where will your next clip go?"
            text="Add your YouTube or Instagram destination. TikTok uses an export handoff."
          />
        )}
      </div>
      <div className="info-note">
        <ShieldCheck size={17} />
        <span>
          Configured means environment variables are present. Live API access,
          app review and granted scopes must still be verified with your own
          account.
        </span>
      </div>
    </>
  );
}
export function SettingsPage({
  studio,
  perform,
  busy,
}: {
  studio: Studio;
  perform: Perform;
  busy: boolean;
}) {
  const s = studio.settings;
  return (
    <div className="settings-layout">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Autonomy, with control</h2>
            <p>Your settings apply at the next worker step.</p>
          </div>
          <Settings2 size={20} />
        </div>
        <div className="setting-row">
          <div>
            <h3>Autopilot</h3>
            <p>
              Approve eligible clips and fill the publishing queue
              automatically.
            </p>
          </div>
          <Toggle
            label="Autopilot"
            checked={s.autopilot}
            onChange={() =>
              void perform(
                () => api("/settings", { autopilot: !s.autopilot }, "PATCH"),
                "Autopilot updated",
              )
            }
          />
        </div>
        <div className="setting-row">
          <div>
            <h3>Strategy learning</h3>
            <p>Use measured 24-hour cohorts to inform future clipping.</p>
          </div>
          <Toggle
            label="Strategy learning"
            checked={s.learning_enabled}
            onChange={() =>
              void perform(
                () =>
                  api(
                    "/settings",
                    { learning_enabled: !s.learning_enabled },
                    "PATCH",
                  ),
                "Learning settings updated",
              )
            }
          />
        </div>
        <div className="setting-row">
          <div>
            <h3>Stop all posting</h3>
            <p>
              Stops new publishing attempts. An API request already sent may
              complete.
            </p>
          </div>
          <Toggle
            label="Stop all posting"
            checked={s.stop_all_posting}
            onChange={() =>
              void perform(
                () =>
                  api(
                    "/settings",
                    { stop_all_posting: !s.stop_all_posting },
                    "PATCH",
                  ),
                "Posting control updated",
              )
            }
          />
        </div>
        <form
          className="settings-form"
          key={JSON.stringify([
            s.timezone,
            s.posting_times,
            s.daily_limit,
            s.min_interval,
            s.thresholds,
          ])}
          onSubmit={async (e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            await perform(
              () =>
                api(
                  "/settings",
                  {
                    timezone: f.get("timezone"),
                    posting_times: String(f.get("times"))
                      .split(",")
                      .map((x) => x.trim()),
                    daily_limit: Number(f.get("daily")),
                    min_interval: Number(f.get("interval")),
                    thresholds: {
                      priority: Number(f.get("priority")),
                      approved: Number(f.get("approved")),
                      reserve: Number(f.get("reserve")),
                    },
                  },
                  "PATCH",
                ),
              "Posting rules saved",
            );
          }}
        >
          <h3>Posting rhythm</h3>
          <div className="form-grid">
            <label>
              Timezone
              <input name="timezone" defaultValue={s.timezone} required />
            </label>
            <label>
              Daily posts per platform
              <input
                name="daily"
                type="number"
                min="1"
                max="30"
                defaultValue={s.daily_limit}
                required
              />
            </label>
            <label>
              Posting times
              <input
                name="times"
                defaultValue={s.posting_times.join(", ")}
                required
              />
            </label>
            <label>
              Minimum interval · minutes
              <input
                name="interval"
                type="number"
                min="15"
                max="1440"
                defaultValue={s.min_interval}
                required
              />
            </label>
          </div>
          <h3>Selection thresholds</h3>
          <div className="form-grid three">
            {["priority", "approved", "reserve"].map((t) => (
              <label key={t}>
                {t}
                <input
                  name={t}
                  type="number"
                  min="0"
                  max="100"
                  defaultValue={s.thresholds[t]}
                  required
                />
              </label>
            ))}
          </div>
          <button className="button primary" disabled={busy}>
            Save posting rules <Check size={16} />
          </button>
        </form>
      </section>
      <div>
        <section className="panel budget-panel">
          <div className="panel-heading">
            <div>
              <h2>Daily guardrails</h2>
              <p>Configured in your .env file</p>
            </div>
            <ShieldCheck size={20} />
          </div>
          {Object.entries(studio.limits).map(([k, v]) => (
            <div className="budget-row" key={k}>
              <span>{k.replaceAll("_", " ")}</span>
              <b>
                {k === "ai_cost" ? "$" : ""}
                {number(v)}
              </b>
            </div>
          ))}
          <p>
            Credit and AI reservations happen before paid work starts. Budget
            exhaustion holds the job for review.
          </p>
        </section>
        <section className="panel policy-panel">
          <h2>Content filters</h2>
          <p>Flag selected categories for manual review.</p>
          {[
            "hate",
            "sexual_content",
            "violence",
            "self_harm",
            "illegal_activity",
            "personal_information",
            "copyright",
          ].map((flag) => (
            <label className="checkbox-label" key={flag}>
              <input
                type="checkbox"
                checked={s.policy_filters.includes(flag)}
                onChange={() =>
                  void perform(
                    () =>
                      api(
                        "/settings",
                        {
                          policy_filters: s.policy_filters.includes(flag)
                            ? s.policy_filters.filter((f) => f !== flag)
                            : [...s.policy_filters, flag],
                        },
                        "PATCH",
                      ),
                    "Content filters updated",
                  )
                }
              />
              {flag.replaceAll("_", " ")}
            </label>
          ))}
        </section>
      </div>
    </div>
  );
}
