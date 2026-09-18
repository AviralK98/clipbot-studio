"use client";
import { useEffect, useRef } from "react";
import {
  X,
  Check,
  ArrowUpRight,
  Play,
  Film,
  Sparkles,
  MoreHorizontal,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Clip, number } from "@/lib/types";

export function Badge({
  children,
  kind = "neutral",
}: {
  children: React.ReactNode;
  kind?: string;
}) {
  return <span className={"badge " + kind}>{children}</span>;
}
export function Empty({
  title,
  text,
  action,
}: {
  title: string;
  text: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Sparkles size={23} />
      </div>
      <h3>{title}</h3>
      <p>{text}</p>
      {action}
    </div>
  );
}
export function Modal({
  title,
  subtitle,
  children,
  onClose,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prior = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab") {
        const nodes = panel.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled),input,select,textarea,a[href],[tabindex="0"]',
        );
        if (!nodes?.length) return;
        const first = nodes[0],
          last = nodes[nodes.length - 1];
        if (
          e.shiftKey &&
          (document.activeElement === first ||
            document.activeElement === panel.current)
        ) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    const old = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = old;
      prior?.focus();
    };
  }, [onClose]);
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panel}
        tabIndex={-1}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="modal-head">
          <div>
            <h2>{title}</h2>
            {subtitle && <p>{subtitle}</p>}
          </div>
          <button
            className="icon-button"
            onClick={onClose}
            aria-label="Close dialog"
          >
            <X size={20} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
export function Stat({
  label,
  value,
  detail,
  icon: Icon,
}: {
  label: string;
  value: string;
  detail: string;
  icon: typeof Film;
}) {
  return (
    <article className="stat">
      <div className="stat-label">
        {label}
        <Icon size={17} />
      </div>
      <strong>{value}</strong>
      <div className="stat-detail">{detail}</div>
    </article>
  );
}
export function ReachChart({
  data,
}: {
  data: { date: string; views: number }[];
}) {
  return (
    <div
      className="chart"
      role="img"
      aria-label={
        "Observed views: " + data.map((d) => d.date + ": " + d.views).join(", ")
      }
    >
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart
          data={data}
          margin={{ left: -25, right: 12, top: 12, bottom: 0 }}
        >
          <defs>
            <linearGradient id="reachFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#c3f879" stopOpacity={0.26} />
              <stop offset="100%" stopColor="#c3f879" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid
            stroke="#242930"
            vertical={false}
            strokeDasharray="3 6"
          />
          <XAxis
            dataKey="date"
            tickFormatter={(v) =>
              new Date(v + "T12:00:00Z").toLocaleDateString("en-GB", {
                weekday: "short",
              })
            }
            axisLine={false}
            tickLine={false}
            tick={{ fill: "#8e969f", fontSize: 11 }}
            dy={12}
          />
          <YAxis
            axisLine={false}
            tickLine={false}
            tickFormatter={number}
            tick={{ fill: "#76808b", fontSize: 10 }}
          />
          <Tooltip
            contentStyle={{
              background: "#171c22",
              border: "1px solid #333d45",
              borderRadius: 10,
              color: "#e8eee3",
            }}
            formatter={(v) => [number(Number(v)), "Observed views"]}
          />
          <Area
            isAnimationActive={false}
            type="monotone"
            dataKey="views"
            stroke="#c3f879"
            strokeWidth={2.5}
            fill="url(#reachFill)"
            activeDot={{ r: 5, fill: "#c3f879" }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
export function ClipCard({
  clip,
  onClick,
  compact = false,
}: {
  clip: Clip;
  onClick: () => void;
  compact?: boolean;
}) {
  const palette =
    Number.parseInt(clip.id.replaceAll("-", "").slice(0, 6), 16) % 4;
  return (
    <button
      className={"clip-card " + (compact ? "compact" : "")}
      onClick={onClick}
    >
      <div className={"clip-art palette-" + palette}>
        {clip.storage_key ? (
          <video
            src={"/api/clips/" + clip.id + "/media#t=1"}
            preload="metadata"
            muted
          />
        ) : (
          <>
            <div className="art-grid" />
            <div className="art-orb" />
            <div className="sound-bars">
              {Array.from({ length: 23 }, (_, i) => (
                <i
                  key={i}
                  style={{ height: 12 + ((i * 13 + palette * 9) % 43) }}
                />
              ))}
            </div>
            <div className="art-copy">
              <span>BUILDER NOTES</span>
              <h4>{clip.title}</h4>
            </div>
          </>
        )}
        <span className="provider-tag">
          <span className={"provider-dot " + clip.provider} />
          {clip.provider === "opus" ? "OpusClip" : "Vizard"}
        </span>
        <span className="duration">{Math.round(clip.duration)}s</span>
        <div className="play-button">
          <Play size={17} fill="currentColor" />
        </div>
        {clip.demo && <span className="fixture-label">DEVELOPMENT SAMPLE</span>}
      </div>
      <div className="clip-info">
        <div className="clip-title-row">
          <h3>{clip.title}</h3>
          <span
            className={
              "score " + ((clip.overall_score || 0) >= 90 ? "high" : "")
            }
          >
            {clip.overall_score == null ? "—" : Math.round(clip.overall_score)}
          </span>
        </div>
        <p>{clip.source || clip.topic}</p>
        <div className="clip-footer">
          <Badge kind={clip.status}>{clip.status}</Badge>
          <span>{clip.topic}</span>
        </div>
      </div>
    </button>
  );
}
export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      className={"toggle " + (checked ? "on" : "")}
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={onChange}
    >
      <span>{checked && <Check size={10} />}</span>
    </button>
  );
}
