"use client";
import { useState } from "react";
import {
  ArrowRight,
  Check,
  ExternalLink,
  Film,
  Plus,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { api, Studio } from "@/lib/types";
import { Dialog } from "./dashboard";
import { Perform } from "./pages";
import { Badge, Modal } from "./ui";
export function StudioDialogs({
  dialog,
  close,
  studio,
  busy,
  perform,
  error,
}: {
  dialog: Dialog;
  close: () => void;
  studio: Studio;
  busy: boolean;
  perform: Perform;
  error: string;
}) {
  const [step, setStep] = useState(0),
    [formError, setFormError] = useState("");
  if (!dialog) return null;
  const submit = async (action: () => Promise<unknown>, message: string) => {
    setFormError("");
    if (await perform(action, message)) close();
    else setFormError("Could not save. Check the values and try again.");
  };
  if (dialog.type === "setup") {
    const steps = [
      {
        name: "Connect Vizard",
        body: "Add VIZARD_API_KEY to the project .env file. API access and credits are required on your provider account.",
        vars: ["VIZARD_API_KEY"],
        url: "https://docs.vizard.ai/docs/quickstart",
      },
      {
        name: "Connect OpusClip",
        body: "Set your API key and organization. For autonomous completion, set PUBLIC_API_BASE_URL and the signing key OPUS_WEBHOOK_SECRET to your organization’s first API secret.",
        vars: [
          "OPUS_API_KEY",
          "OPUS_ORG_ID",
          "OPUS_WEBHOOK_SECRET",
          "PUBLIC_API_BASE_URL",
        ],
        url: "https://help.opus.pro/api-reference/quickstart",
      },
      {
        name: "Connect your channels",
        body: "YouTube needs an OAuth refresh token and upload permissions. Instagram needs a professional account and Page access token. Register destinations on Connections after setting credentials. TikTok uses manual export because Direct Post excludes personal utilities.",
        vars: [
          "YOUTUBE_CLIENT_ID",
          "YOUTUBE_CLIENT_SECRET",
          "YOUTUBE_REFRESH_TOKEN",
          "INSTAGRAM_ACCESS_TOKEN",
          "INSTAGRAM_USER_ID",
        ],
        url: "https://developers.google.com/youtube/v3/guides/uploading_a_video",
      },
      {
        name: "Add an authorized source",
        body: "Add a source you own or have permission to reuse. Record the authorization and choose permitted platforms. YouTube duration verification also requires YOUTUBE_DATA_API_KEY.",
        vars: ["YOUTUBE_DATA_API_KEY"],
        url: "",
      },
      {
        name: "Set your limits",
        body: "Choose daily posting caps and intervals in Settings. Configure source minutes, provider credits and AI spend limits in .env. Restart the backend and worker after editing environment variables.",
        vars: [
          "MAX_SOURCE_MINUTES_PER_DAY",
          "MAX_VIZARD_CREDITS_PER_DAY",
          "MAX_OPUS_CREDITS_PER_DAY",
          "MAX_AI_COST_PER_DAY",
        ],
        url: "",
      },
      {
        name: "Let your studio work",
        body: "Free local review is ready without OpenAI or Anthropic keys. Add a video, then review the clips and extracted captions. Local scores only check transcript structure; approve each clip yourself. Paid AI review remains optional for later. Vizard and OpusClip processing still uses provider credits.",
        vars: [],
        url: "",
      },
    ];
    const current = steps[step];
    return (
      <Modal
        title="Your studio, ready to run."
        subtitle="Six steps to a connected workflow. Keep secrets in .env, never in chat."
        onClose={close}
      >
        <div className="setup-steps">
          {steps.map((s, i) => (
            <button
              key={s.name}
              onClick={() => setStep(i)}
              className={i === step ? "current" : i < step ? "visited" : ""}
            >
              <span>{i < step ? <Check size={13} /> : i + 1}</span>
              <small>{s.name}</small>
            </button>
          ))}
        </div>
        <div className="setup-body">
          <span className="eyebrow">STEP {step + 1} OF 6</span>
          <h3>{current.name}</h3>
          <p>{current.body}</p>
          <div className="setup-env">
            {current.vars.map((v) => (
              <code key={v}>{v}=</code>
            ))}
          </div>
          {current.url && (
            <a
              className="text-link"
              href={current.url}
              target="_blank"
              rel="noreferrer"
            >
              Official documentation <ExternalLink size={14} />
            </a>
          )}
          <div className="setup-status">
            {studio.integrations.filter((i) => i.configured).length} of 5
            integrations ready, including free local review. You only need to
            connect the services you use.
          </div>
        </div>
        <div className="modal-actions">
          <button
            className="button"
            disabled={step === 0}
            onClick={() => setStep(step - 1)}
          >
            Back
          </button>
          <button
            className="button primary"
            onClick={() => (step === 5 ? close() : setStep(step + 1))}
          >
            {step === 5 ? "Open my studio" : "Next step"}
            <ArrowRight size={15} />
          </button>
        </div>
      </Modal>
    );
  }
  if (dialog.type === "source")
    return (
      <Modal
        title={dialog.source ? "Edit your source" : "Add a content source"}
        subtitle="A record of content you own or have permission to share."
        onClose={close}
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            const body = {
              name: f.get("name"),
              url: f.get("url"),
              kind: f.get("kind"),
              authorization_type: f.get("authorization_type"),
              authorization_note: f.get("authorization_note"),
              authorized_platforms: f.getAll("platform"),
              category: f.get("category"),
              routing: f.get("routing"),
              enabled: dialog.source?.enabled ?? true,
            };
            void submit(
              () =>
                api(
                  "/sources" + (dialog.source ? "/" + dialog.source.id : ""),
                  body,
                  dialog.source ? "PUT" : "POST",
                ),
              "Source saved",
            );
          }}
        >
          <div className="form-grid">
            <label>
              Source name
              <input
                name="name"
                defaultValue={dialog.source?.name}
                placeholder="The Builder's Journal"
                required
                maxLength={200}
              />
            </label>
            <label>
              Source type
              <select
                name="kind"
                defaultValue={dialog.source?.kind || "manual"}
              >
                <option value="manual">Manual video URLs</option>
                <option value="youtube_channel">YouTube channel</option>
                <option value="youtube_playlist">YouTube playlist</option>
                <option value="rss">Video RSS feed</option>
                <option value="local">Local folder</option>
              </select>
            </label>
            <label className="full">
              Source URL or relative local folder
              <input
                name="url"
                defaultValue={dialog.source?.url}
                placeholder="https://www.youtube.com/@your-channel"
                required
              />
            </label>
            <label>
              Content category
              <input
                name="category"
                defaultValue={dialog.source?.category || "podcast"}
                required
              />
            </label>
            <label>
              Clipping mode
              <select
                name="routing"
                defaultValue={dialog.source?.routing || "dual"}
              >
                <option value="dual">Dual engine · Vizard + Opus</option>
                <option value="vizard">Vizard</option>
                <option value="opus">OpusClip</option>
                <option value="learned">Learn from performance</option>
              </select>
            </label>
            <label>
              Authorization
              <select
                name="authorization_type"
                defaultValue={dialog.source?.authorization_type || "owner"}
              >
                <option value="owner">I own this content</option>
                <option value="licensed">Licensed for reuse</option>
                <option value="permission">Permission from the owner</option>
              </select>
            </label>
            <fieldset>
              <legend>Permitted platforms</legend>
              <div className="checkbox-group">
                {["youtube", "instagram", "tiktok"].map((p) => (
                  <label key={p} className="checkbox-label">
                    <input
                      name="platform"
                      type="checkbox"
                      value={p}
                      defaultChecked={
                        dialog.source
                          ? dialog.source.authorized_platforms.includes(p)
                          : p === "youtube"
                      }
                    />
                    {p}
                  </label>
                ))}
              </div>
            </fieldset>
            <label className="full">
              Authorization record
              <textarea
                name="authorization_note"
                defaultValue={dialog.source?.authorization_note}
                placeholder="Describe ownership, or record the permission / license and its scope."
                required
                maxLength={3000}
              />
            </label>
          </div>
          {formError && (
            <p className="inline-error" role="alert">
              {error || formError}
            </p>
          )}
          <div className="modal-actions">
            <button type="button" className="button" onClick={close}>
              Cancel
            </button>
            <button className="button primary" disabled={busy}>
              <ShieldCheck size={16} />
              Save source
            </button>
          </div>
        </form>
      </Modal>
    );
  if (dialog.type === "video")
    return (
      <Modal
        title="One video. More possibilities."
        subtitle="Submit an authorized video to your configured clipping engines."
        onClose={close}
      >
        {studio.sources.length ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              void submit(
                () =>
                  api("/videos", {
                    source_id: f.get("source_id"),
                    url: f.get("url"),
                    title: f.get("title"),
                    duration: Number(f.get("duration")) * 60,
                  }),
                "Video added to the processing queue",
              );
            }}
          >
            <div className="video-intro">
              <Film size={28} />
              <div>
                <h3>Your next batch starts here</h3>
                <p>The source’s routing rule determines which engines run.</p>
              </div>
            </div>
            <label>
              Authorized source
              <select name="source_id" required>
                {studio.sources
                  .filter((s) => s.enabled)
                  .map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                      {s.demo ? " (development sample)" : ""}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Video title
              <input
                name="title"
                placeholder="A conversation worth sharing"
                required
                maxLength={300}
              />
            </label>
            <label>
              Video URL
              <input
                name="url"
                type="url"
                placeholder="https://www.youtube.com/watch?v=…"
                required
              />
            </label>
            <label>
              Source duration · minutes
              <input
                name="duration"
                type="number"
                min="0.1"
                max="600"
                step="0.1"
                placeholder="45"
                required
              />
            </label>
            <p className="form-hint">
              YouTube duration is verified through the Data API. For other URLs,
              enter the full, accurate duration so credit reservations reflect
              expected usage.
            </p>
            {formError && (
              <p className="inline-error" role="alert">
                {error || formError}
              </p>
            )}
            <div className="modal-actions">
              <button type="button" className="button" onClick={close}>
                Cancel
              </button>
              <button className="button primary" disabled={busy}>
                <Sparkles size={16} />
                Start clipping
              </button>
            </div>
          </form>
        ) : (
          <div className="empty">
            <h3>Add your first source</h3>
            <p>
              Open Sources and record your authorization before submitting a
              video.
            </p>
            <a className="button primary" href="/sources">
              Open sources <ArrowRight size={15} />
            </a>
          </div>
        )}
      </Modal>
    );
  if (dialog.type === "account")
    return (
      <Modal
        title="Add a publishing destination"
        subtitle="Credentials stay in .env. This record identifies your configured channel."
        onClose={close}
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            void submit(
              () =>
                api("/accounts", {
                  platform: f.get("platform"),
                  name: f.get("name"),
                  external_id: f.get("external_id"),
                  daily_limit: Number(f.get("daily_limit")),
                }),
              "Destination added",
            );
          }}
        >
          <label>
            Platform
            <select name="platform">
              <option value="youtube">YouTube Shorts</option>
              <option value="instagram">Instagram Reels</option>
              <option value="tiktok">TikTok · export only</option>
            </select>
          </label>
          <label>
            Channel name
            <input name="name" placeholder="Builder Notes" required />
          </label>
          <label>
            Channel or account ID
            <input name="external_id" placeholder="Your platform account ID" />
          </label>
          <label>
            Daily post limit
            <input
              name="daily_limit"
              type="number"
              min="1"
              max="30"
              defaultValue={3}
            />
          </label>
          <p className="form-hint">
            The environment credential adapter currently supports one live
            account per platform. Adding a record does not perform OAuth or
            verify API access.
          </p>
          {formError && (
            <p className="inline-error" role="alert">
              {error || formError}
            </p>
          )}
          <div className="modal-actions">
            <button type="button" className="button" onClick={close}>
              Cancel
            </button>
            <button disabled={busy} className="button primary">
              Add destination <Plus size={15} />
            </button>
          </div>
        </form>
      </Modal>
    );
  if (dialog.type === "schedule" && dialog.clip)
    return (
      <Modal
        title="Give this moment a time."
        subtitle={dialog.clip.title}
        onClose={close}
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            const time = String(f.get("time") || "");
            void submit(
              () =>
                api("/queue", {
                  clip_id: dialog.clip!.id,
                  account_id: f.get("account"),
                  ...(time
                    ? { scheduled_at: new Date(time).toISOString() }
                    : {}),
                }),
              "Clip scheduled",
            );
          }}
        >
          <label>
            Publishing destination
            <select name="account" required>
              {studio.accounts
                .filter((a) => a.enabled && a.demo === dialog.clip!.demo)
                .map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
            </select>
          </label>
          <label>
            Posting time · your device timezone
            <input name="time" type="datetime-local" />
          </label>
          <p className="form-hint">
            Leave the time empty to use the next slot in{" "}
            {studio.settings.timezone}. Daily limits and minimum intervals apply
            to both automatic and custom times.
          </p>
          {formError && (
            <p className="inline-error" role="alert">
              {error || formError}
            </p>
          )}
          <div className="modal-actions">
            <button type="button" className="button" onClick={close}>
              Cancel
            </button>
            <button
              className="button primary"
              disabled={
                busy ||
                !studio.accounts.some(
                  (a) => a.enabled && a.demo === dialog.clip!.demo,
                )
              }
            >
              Schedule clip <ArrowRight size={15} />
            </button>
          </div>
        </form>
      </Modal>
    );
  if (dialog.type === "metrics" && dialog.post)
    return (
      <Modal
        title="Attach a performance snapshot"
        subtitle="Use measured values from your platform analytics export. Leave unavailable fields blank."
        onClose={close}
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            const body = Object.fromEntries(
              Array.from(f.entries()).map(([k, v]) => [
                k,
                String(v) === "" ? null : Number(v),
              ]),
            );
            void submit(
              () =>
                api(
                  "/publications/" + dialog.post!.publication!.id + "/metrics",
                  body,
                ),
              "Performance snapshot recorded",
            );
          }}
        >
          <label>
            Checkpoint
            <select name="checkpoint_hours">
              {[1, 6, 24, 72, 168].map((h) => (
                <option key={h} value={h}>
                  {h === 168 ? "7 days" : h + " hours"}
                </option>
              ))}
            </select>
          </label>
          <div className="form-grid">
            {[
              "views",
              "likes",
              "comments",
              "shares",
              "followers_gained",
              "watch_time_minutes",
              "average_watch_percentage",
            ].map((k) => (
              <label key={k}>
                {k.replaceAll("_", " ")}
                <input
                  name={k}
                  type="number"
                  min="0"
                  step={k.includes("watch") ? "0.1" : "1"}
                />
              </label>
            ))}
          </div>
          {formError && (
            <p className="inline-error" role="alert">
              {error || formError}
            </p>
          )}
          <div className="modal-actions">
            <button type="button" className="button" onClick={close}>
              Cancel
            </button>
            <button className="button primary" disabled={busy}>
              Save snapshot
            </button>
          </div>
        </form>
      </Modal>
    );
  if (dialog.type === "publication" && dialog.post)
    return (
      <Modal
        title="Record a confirmed publication"
        subtitle="Use this when an interrupted upload already appeared on your channel. This records the result without uploading again."
        onClose={close}
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            void submit(
              () =>
                api("/queue/" + dialog.post!.id + "/reconcile", {
                  external_id: f.get("external_id"),
                  published_at: new Date(
                    String(f.get("published_at")),
                  ).toISOString(),
                  publication_confirmed: f.get("confirmed") === "on",
                }),
              "Publication recorded; analytics checkpoints queued",
            );
          }}
        >
          <label>
            Platform publication ID
            <input
              name="external_id"
              required
              pattern="[a-zA-Z0-9._-]+"
              maxLength={200}
            />
          </label>
          <label>
            Actual publication time · your device timezone
            <input name="published_at" type="datetime-local" required />
          </label>
          <label className="checkbox-label">
            <input name="confirmed" type="checkbox" required />I verified this
            exact clip and publication ID on the destination channel.
          </label>
          {formError && (
            <p className="inline-error" role="alert">
              {error || formError}
            </p>
          )}
          <div className="modal-actions">
            <button type="button" className="button" onClick={close}>
              Cancel
            </button>
            <button className="button primary" disabled={busy}>
              Record publication
            </button>
          </div>
        </form>
      </Modal>
    );
  if (dialog.type === "reconcile") {
    const project = studio.projects.find((p) => p.id === dialog.projectId);
    return (
      <Modal
        title="Reconcile a provider project"
        subtitle="Find the existing project in your provider dashboard. Attaching its ID avoids another paid submission."
        onClose={close}
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            void submit(
              () =>
                api("/projects/" + dialog.projectId + "/reconcile", {
                  external_id: f.get("external_id"),
                  completion_confirmed: f.get("completed") === "on",
                }),
              "Project reconciled and import queued",
            );
          }}
        >
          <label>
            External project ID
            <input
              name="external_id"
              defaultValue={project?.external_id || ""}
              required
            />
          </label>
          <label className="checkbox-label">
            <input name="completed" type="checkbox" />I verified in the provider
            dashboard that generation is complete.
          </label>
          {formError && (
            <p className="inline-error" role="alert">
              {error || formError}
            </p>
          )}
          <div className="modal-actions">
            <button type="button" className="button" onClick={close}>
              Cancel
            </button>
            <button className="button primary" disabled={busy}>
              Attach project
            </button>
          </div>
        </form>
      </Modal>
    );
  }
  return null;
}
