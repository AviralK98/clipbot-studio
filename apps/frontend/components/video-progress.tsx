"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  Check,
  Film,
  Loader2,
  X,
} from "lucide-react";
import { RecentVideo } from "@/lib/types";

const STEPS = [
  { id: "sending", label: "Sent to engines" },
  { id: "clipping", label: "Finding clips" },
  { id: "scoring", label: "Scoring" },
  { id: "done", label: "Ready" },
] as const;

const ACTIVE = ["sending", "clipping", "scoring"];

function minutes(from: string, to: number) {
  return Math.max(0, Math.round((to - new Date(from).getTime()) / 60000));
}

function span(m: number) {
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

function ago(iso: string, now: number) {
  const m = minutes(iso, now);
  return m < 1 ? "just now" : `${span(m)} ago`;
}

function summary(v: RecentVideo) {
  const c = v.clips;
  if (v.stage === "sending") return "Sending the video to the clipping engines.";
  if (v.stage === "clipping")
    return "The engines are finding the best moments. Long videos take a while; this card updates by itself.";
  if (v.stage === "scoring")
    return `Scoring the clips: ${c.scored} of ${c.found} done. Then ClipBot picks the best ones.`;
  if (v.stage === "failed") return "Neither clipping engine could process this video.";
  if (!c.found) return "The engines didn't find any clips in this video.";
  const parts = [
    [c.approved, "selected"],
    [c.review, "waiting for your review"],
    [c.rejected, "rejected"],
  ].filter(([n]) => n);
  return `${c.found} clips found: ${parts.map(([n, what]) => `${n} ${what}`).join(", ")}.`;
}

type Engine = RecentVideo["engines"][number];
type Confirm = (projectId: string, externalId: string) => Promise<unknown>;

function engineState(e: Engine) {
  if (e.status === "complete") return { icon: "done", text: `${e.clips} clips` };
  if (e.status === "failed") return { icon: "failed", text: "failed" };
  if (e.problem) return { icon: "stuck", text: "stuck" };
  if (e.status === "needs_reconciliation") return { icon: "stuck", text: "needs a check" };
  if (e.confirmed) return { icon: "working", text: "importing clips" };
  if (e.needs_confirmation) return { icon: "working", text: "clipping in OpusClip" };
  if (e.status === "processing") return { icon: "working", text: "finding clips" };
  return { icon: "working", text: e.status === "submitting" ? "sending" : "starting" };
}

function ConfirmFinished({ engine, onConfirm }: { engine: Engine; onConfirm: Confirm }) {
  const [asking, setAsking] = useState(false),
    [sending, setSending] = useState(false);
  return (
    <div className="vp-confirm">
      <p>
        {engine.name} can’t tell ClipBot when it’s done. Once this project shows
        its clips in {engine.name}, confirm it here to bring them in.
      </p>
      {asking ? (
        <div className="vp-confirm-actions">
          <span>Is it finished in {engine.name}, with all its clips?</span>
          <button
            className="button small primary"
            disabled={sending}
            onClick={async () => {
              setSending(true);
              await onConfirm(engine.project_id, engine.external_id || "");
              setSending(false);
              setAsking(false);
            }}
          >
            {sending ? <Loader2 size={13} className="spin" /> : <Check size={13} />}
            Yes, import the clips
          </button>
          <button className="button small" onClick={() => setAsking(false)}>
            Not yet
          </button>
        </div>
      ) : (
        <button className="button small" onClick={() => setAsking(true)}>
          It’s finished in {engine.name}
        </button>
      )}
    </div>
  );
}

function StepIcon({ state }: { state: string }) {
  if (state === "done") return <Check size={11} />;
  if (state === "failed") return <X size={11} />;
  if (state === "current") return <Loader2 size={11} className="spin" />;
  return null;
}

function Steps({ stage }: { stage: RecentVideo["stage"] }) {
  const at = stage === "failed" ? 1 : STEPS.findIndex((s) => s.id === stage);
  return (
    <ol className="vp-steps" aria-label="Progress">
      {STEPS.map((step, i) => {
        const state =
          stage === "done" || i < at
            ? "done"
            : i === at
              ? stage === "failed"
                ? "failed"
                : "current"
              : "todo";
        return (
          <li
            key={step.id}
            className={"vp-step " + state}
            aria-current={state === "current" ? "step" : undefined}
          >
            <span className="vp-dot">
              <StepIcon state={state} />
            </span>
            {step.label}
          </li>
        );
      })}
    </ol>
  );
}

function VideoRow({
  video,
  now,
  onConfirm,
}: {
  video: RecentVideo;
  now: number;
  onConfirm: Confirm;
}) {
  const problems = [
    ...(video.problem ? [{ name: "Setup", problem: video.problem }] : []),
    ...(video.files.problem
      ? [{ name: "Saving files", problem: video.files.problem }]
      : []),
    ...video.engines
      .filter((e) => e.problem)
      .map((e) => ({ name: e.name, problem: e.problem as string })),
  ];
  const active = ACTIVE.includes(video.stage);
  return (
    <div className="vp-row">
      {video.thumbnail ? (
        <img className="vp-thumb" src={video.thumbnail} alt="" loading="lazy" />
      ) : (
        <span className="vp-thumb vp-thumb-empty">
          <Film size={18} />
        </span>
      )}
      <div className="vp-body">
        <div className="vp-title">
          <b title={video.title}>{video.title}</b>
          <small>
            {span(Math.round(video.duration / 60))} video · added{" "}
            {ago(video.added_at, now)}
            {active && ` · working for ${span(minutes(video.added_at, now))}`}
            {video.finished_at &&
              ` · took ${span(minutes(video.added_at, new Date(video.finished_at).getTime()))}`}
          </small>
        </div>
        <Steps stage={video.stage} />
        <div className="vp-engines">
          {video.engines.map((e) => {
            const s = engineState(e);
            return (
              <span key={e.provider} className={"vp-engine " + s.icon}>
                {s.icon === "working" && <Loader2 size={12} className="spin" />}
                {s.icon === "done" && <Check size={12} />}
                {s.icon === "failed" && <X size={12} />}
                {s.icon === "stuck" && <AlertTriangle size={12} />}
                <b>{e.name}</b> {s.text}
              </span>
            );
          })}
        </div>
        <p className="vp-summary">{summary(video)}</p>
        {video.files.pending > 0 && (
          <p className="vp-files">
            <Loader2 size={12} className="spin" />
            <span>
              Saving the video files: {video.files.saved} of{" "}
              {video.files.saved + video.files.pending} done. You can review
              clips now; each one can be posted once its file is saved.
            </span>
          </p>
        )}
        {video.engines
          .filter((e) => e.needs_confirmation)
          .map((e) => (
            <ConfirmFinished key={e.provider} engine={e} onConfirm={onConfirm} />
          ))}
        {problems.map((p) => (
          <p className="vp-problem" key={p.name}>
            <AlertTriangle size={13} />
            <span>
              <b>{p.name}:</b> {p.problem}
            </span>
          </p>
        ))}
        {video.stage === "done" && video.clips.found > 0 && (
          <Link className="text-link" href="/clips">
            Review clips <ArrowRight size={14} />
          </Link>
        )}
      </div>
    </div>
  );
}

/** Shows what each recently added video is doing; unfinished ones appear on every page. */
export function VideoProgress({
  videos,
  showFinished,
  onConfirm,
}: {
  videos: RecentVideo[];
  showFinished: boolean;
  onConfirm: Confirm;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(id);
  }, []);
  const shown = videos.filter((v) => showFinished || ACTIVE.includes(v.stage));
  if (!shown.length) return null;
  const working = videos.filter((v) => ACTIVE.includes(v.stage)).length;
  return (
    <section className="panel vp-panel" aria-live="polite">
      <div className="panel-heading">
        <div>
          <h2>Your videos</h2>
          <p>Recently added videos and how far along they are.</p>
        </div>
        {working > 0 && (
          <span className="badge running vp-count">
            <Loader2 size={11} className="spin" />
            {working} in progress
          </span>
        )}
      </div>
      <div className="vp-list">
        {shown.map((v) => (
          <VideoRow key={v.id} video={v} now={now} onConfirm={onConfirm} />
        ))}
      </div>
    </section>
  );
}
