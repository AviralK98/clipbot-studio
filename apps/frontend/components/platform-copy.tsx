"use client";
import { useState } from "react";
import { Check, Copy } from "lucide-react";

type CopyData = {
  title?: string;
  caption?: string;
  description?: string;
  hashtags?: string[];
};
type Hook = { style: string; text: string; evidence_quote: string };
export function PlatformCopy({
  metadata,
}: {
  metadata: Record<string, unknown>;
}) {
  const [platform, setPlatform] = useState("youtube");
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  const data = metadata[platform] as CopyData | undefined;
  const hooks = (metadata.hooks || []) as Hook[];
  const content = [
    data?.title,
    platform === "youtube" ? data?.description : data?.caption,
    data?.hashtags?.join(" "),
  ]
    .filter(Boolean)
    .join("\n\n");
  return (
    <div className="platform-copy">
      {metadata.review_mode === "local" && (
        <p className="form-hint">
          Free local review. Copy is extracted from the transcript; the score is
          a simple heuristic, not an AI assessment. Review the video and approve
          it manually.
        </p>
      )}
      <div className="filter-chips" aria-label="Platform copy">
        {["youtube", "instagram", "tiktok"].map((p) => (
          <button
            key={p}
            className={platform === p ? "active" : ""}
            onClick={() => {
              setPlatform(p);
              setCopied(false);
              setCopyError(false);
            }}
          >
            {p === "youtube"
              ? "YouTube"
              : p === "instagram"
                ? "Instagram"
                : "TikTok"}
          </button>
        ))}
      </div>
      {data ? (
        <>
          <h4>{data.title}</h4>
          <p className="copy-text">
            {platform === "youtube" ? data.description : data.caption}
          </p>
          <p className="copy-tags">{data.hashtags?.join(" ")}</p>
          <button
            className="button small"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(content);
                setCopied(true);
              } catch {
                setCopyError(true);
              }
            }}
          >
            {copied ? <Check size={14} /> : <Copy size={14} />}{" "}
            {copied ? "Copied" : "Copy for " + platform}
          </button>
          {copyError && (
            <p role="alert" className="form-hint">
              Clipboard access is unavailable. Select and copy the text above.
            </p>
          )}
        </>
      ) : (
        <p className="muted">Copy will appear after clip review.</p>
      )}
      {hooks.length > 0 && (
        <div className="hook-options">
          <h4>Opening ideas</h4>
          <p className="form-hint">
            Text suggestions supported by the transcript.
          </p>
          {hooks.map((h, i) => (
            <div key={i}>
              <span className="eyebrow">{h.style}</span>
              <p>{h.text}</p>
              <blockquote>{h.evidence_quote}</blockquote>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
