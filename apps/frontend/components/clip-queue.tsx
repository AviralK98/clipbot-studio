"use client";
import { useState } from "react";
import { Check, ListOrdered, Loader2, Plus, Upload, X } from "lucide-react";
import { api, Clip, date, Post, Studio } from "@/lib/types";

export type Queued = Map<string, { post: Post; n: number }>;

/** This account's upcoming posts, numbered in the order they'll go out. */
export function queuedFor(posts: Post[], accountId: string): Queued {
  const upcoming = posts
    .filter((p) => p.status === "scheduled" && p.account_id === accountId)
    .sort((a, b) => a.scheduled_at.localeCompare(b.scheduled_at));
  return new Map(upcoming.map((post, i) => [post.clip_id, { post, n: i + 1 }]));
}

/** Approved clips, and ones waiting for review (picking them approves them). Flagged clips need a closer look first. */
export function canPick(clip: Clip, demo: boolean) {
  return (
    clip.demo === demo &&
    !clip.duplicate_of &&
    (clip.status === "approved" ||
      (clip.status === "reserve" && !clip.policy_flags.length))
  );
}

export function defaultQueueAccount(studio: Studio) {
  const live = studio.accounts.filter(
    (a) => a.enabled && a.demo === studio.demo_mode,
  );
  return (live.find((a) => a.platform === "youtube") || live[0])?.id || "";
}

export function PickBox({
  n,
  queuedAt,
  title,
  onToggle,
}: {
  n: number;
  queuedAt: string | null;
  title: string;
  onToggle: () => void;
}) {
  return (
    <>
      <button
        type="button"
        className={"pick-box" + (queuedAt ? " queued" : n ? " picked" : "")}
        aria-pressed={n > 0}
        aria-label={
          queuedAt
            ? `Take “${title}” out of the queue`
            : n
              ? `Unpick “${title}”`
              : `Pick “${title}” for the queue`
        }
        title={queuedAt ? "Untick to take it out of the queue" : undefined}
        onClick={onToggle}
      >
        {n ? <b>{n}</b> : <Plus size={14} />}
      </button>
      {queuedAt && <span className="pick-when">Queued · {queuedAt}</span>}
    </>
  );
}

type Result = {
  queued: { id: string; scheduled_at: string }[];
  skipped: { id: string; title: string; reason: string }[];
};

export function QueueBar({
  studio,
  queued,
  picked,
  setPicked,
  account,
  setAccount,
  refresh,
}: {
  studio: Studio;
  queued: Queued;
  picked: Clip[];
  setPicked: (clips: Clip[]) => void;
  account: string;
  setAccount: (id: string) => void;
  refresh: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false),
    [report, setReport] = useState<string[]>([]),
    [confirmNow, setConfirmNow] = useState(false);
  const settings = studio.settings;
  const accounts = studio.accounts.filter(
    (a) => a.enabled && a.demo === studio.demo_mode,
  );
  const name = accounts.find((a) => a.id === account)?.name || "this channel";
  const upcoming = [...queued.values()].map(({ post, n }) => ({
    n,
    title: post.title,
    when: date(post.scheduled_at, settings.timezone),
  }));
  const lineup = [
    ...upcoming,
    ...picked.map((c, i) => ({
      n: queued.size + i + 1,
      title: c.title,
      when: null as string | null,
    })),
  ];
  const hours = settings.min_interval / 60;
  const count = `${picked.length} ${picked.length === 1 ? "clip" : "clips"}`;
  async function queuePicked(now: boolean) {
    setBusy(true);
    setReport([]);
    setConfirmNow(false);
    try {
      const result = await api<Result>("/queue/batch", {
        clip_ids: picked.map((c) => c.id),
        account_id: account,
        now,
      });
      const done = new Set(result.queued.map((q) => q.id));
      const n = `${result.queued.length} ${result.queued.length === 1 ? "clip" : "clips"}`;
      setPicked(picked.filter((c) => !done.has(c.id)));
      setReport([
        now
          ? `Uploading ${n} to ${name} now, one after another in pick order. Follow them in Publishing queue.`
          : `Queued ${n} to ${name}.`,
        ...result.skipped.map((s) => `Skipped “${s.title}”: ${s.reason}`),
      ]);
      await refresh();
    } catch (e) {
      setReport(["", (e as Error).message]);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel queue-bar" aria-label="Queue picked clips">
      <div className="queue-bar-head">
        <div>
          <h2>
            <ListOrdered size={16} /> Pick clips to post
          </h2>
          <p>
            Tick clips below in the order you want them posted. They go out
            in that order at your posting times ({settings.posting_times.join(", ")}),
            at least {hours % 1 ? `${settings.min_interval} min` : `${hours} h`}{" "}
            apart, or straight away with Upload now. Untick a queued clip to
            take it out; the ones after it move up.
          </p>
        </div>
        <div className="queue-bar-actions">
          <select
            aria-label="Channel to queue to"
            value={account}
            onChange={(e) => {
              setAccount(e.target.value);
              setReport([]);
            }}
          >
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} · {a.platform}
              </option>
            ))}
          </select>
          <button
            className="button primary"
            disabled={busy || !picked.length || !account || settings.stop_all_posting}
            onClick={() => void queuePicked(false)}
          >
            {busy ? <Loader2 size={15} className="spin" /> : <Check size={15} />}
            {picked.length ? `Queue ${count}` : "Queue picked clips"}
          </button>
          <button
            className="button"
            disabled={busy || !picked.length || !account || settings.stop_all_posting}
            onClick={() => setConfirmNow(true)}
          >
            <Upload size={15} />
            {picked.length ? `Upload ${count} now` : "Upload now"}
          </button>
          {picked.length > 0 && (
            <button className="button" disabled={busy} onClick={() => setPicked([])}>
              <X size={15} /> Clear picks
            </button>
          )}
        </div>
      </div>
      {settings.stop_all_posting && (
        <p className="form-hint">Posting is paused. Resume it in Queue first.</p>
      )}
      {confirmNow && picked.length > 0 && (
        <div className="queue-confirm" role="region" aria-label="Confirm upload now">
          <p>
            Upload {count} to {name} right now, one after another in pick
            order? This skips your posting times and spacing; the daily limit
            still applies.
          </p>
          <button
            className="button small primary"
            disabled={busy}
            onClick={() => void queuePicked(true)}
          >
            <Upload size={13} /> Yes, upload now
          </button>
          <button className="button small" onClick={() => setConfirmNow(false)}>
            Cancel
          </button>
        </div>
      )}
      {lineup.length > 0 && (
        <ol className="queue-lineup">
          {lineup.slice(0, 8).map((item) => (
            <li key={item.n} className={item.when ? "" : "pending"}>
              <b>{item.n}</b>
              <span title={item.title}>{item.title}</span>
              <small>{item.when || "picked, not queued yet"}</small>
            </li>
          ))}
          {lineup.length > 8 && (
            <li className="more">+{lineup.length - 8} more</li>
          )}
        </ol>
      )}
      {report.length > 0 && (
        <div className="queue-report" role="status">
          {report.map((line, i) =>
            // The first line is the summary; it's empty when the request itself failed.
            line ? (
              <p key={line} className={i === 0 ? "ok" : ""}>
                {line}
              </p>
            ) : null,
          )}
        </div>
      )}
    </section>
  );
}
