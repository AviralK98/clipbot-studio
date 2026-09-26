"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  KeyRound,
  Loader2,
  Play,
  ShieldCheck,
} from "lucide-react";
import { api, AppConfig, ConfigField, Studio, YouTubeConnection } from "@/lib/types";

type Perform = (action: () => Promise<unknown>, message: string) => Promise<boolean>;

function Field({
  field,
  draft,
  editable,
  onChange,
  onRemove,
}: {
  field: ConfigField;
  draft: string | undefined;
  editable: boolean;
  onChange: (value: string) => void;
  onRemove: () => void;
}) {
  const locked = !editable || field.from_environment;
  return (
    <label className="key-field">
      <span>
        {field.label}
        {field.secret && field.saved && (
          <b className="key-saved">
            <Check size={11} /> saved
          </b>
        )}
      </span>
      {field.choices ? (
        <select
          value={draft ?? field.value ?? ""}
          disabled={locked}
          onChange={(e) => onChange(e.target.value)}
        >
          {field.choices.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      ) : (
        <div className="key-input">
          <input
            type={field.secret ? "password" : "text"}
            autoComplete="off"
            spellCheck={false}
            disabled={locked}
            value={draft ?? (field.secret ? "" : field.value ?? "")}
            placeholder={
              field.from_environment
                ? "Set by an environment variable"
                : field.secret && field.saved
                  ? "Saved. Paste a new one to replace it"
                  : "Paste it here"
            }
            onChange={(e) => onChange(e.target.value)}
          />
          {field.secret && field.saved && !locked && (
            <button type="button" className="button small" onClick={onRemove}>
              Remove
            </button>
          )}
        </div>
      )}
    </label>
  );
}

function ConnectYouTube({
  config,
  onConnected,
}: {
  config: AppConfig;
  onConnected: () => void;
}) {
  const [connection, setConnection] = useState<YouTubeConnection>(config.youtube),
    [error, setError] = useState("");
  const fields = config.groups.find((g) => g.id === "youtube")?.fields || [];
  const ready = fields
    .filter((f) => f.name === "youtube_client_id" || f.name === "youtube_client_secret")
    .every((f) => f.saved);
  useEffect(() => {
    if (connection.status !== "waiting") return;
    const id = setInterval(async () => {
      const next = await api<YouTubeConnection>("/youtube/connect").catch(() => null);
      if (!next || next.status === "waiting") return;
      setConnection(next);
      if (next.status === "connected") onConnected();
    }, 2000);
    return () => clearInterval(id);
  }, [connection.status, onConnected]);
  async function connect() {
    setError("");
    // Open the tab during the click so pop-up blockers allow it, then send it to Google.
    const tab = window.open("", "_blank");
    try {
      const { url } = await api<{ url: string }>("/youtube/connect", {});
      if (tab) tab.location.href = url;
      else window.open(url, "_blank");
      setConnection({ ...connection, status: "waiting", message: "Approve ClipBot in the Google tab that opened.", url });
    } catch (e) {
      tab?.close();
      setError((e as Error).message);
    }
  }
  return (
    <div className="youtube-connect">
      <div>
        <b>
          <Play size={14} />{" "}
          {connection.connected ? "YouTube is connected" : "YouTube isn't connected yet"}
        </b>
        <p>
          {connection.status === "idle"
            ? connection.connected
              ? "Google ends the login every 7 days while your Google app is in Testing; reconnect here when ClipBot asks."
              : ready
                ? "Sign in with the Google account that owns your channel and tick every permission."
                : "Save your OAuth client ID and secret first."
            : connection.message}
        </p>
        {error && <p className="inline-error">{error}</p>}
      </div>
      <button
        type="button"
        className="button primary"
        disabled={!ready || connection.status === "waiting"}
        onClick={() => void connect()}
      >
        {connection.status === "waiting" ? (
          <Loader2 size={15} className="spin" />
        ) : (
          <Play size={15} />
        )}
        {connection.connected ? "Reconnect YouTube" : "Connect YouTube"}
      </button>
    </div>
  );
}

/** Where the owner pastes API keys; they're stored in Windows Credential Manager, not a file. */
export function KeysPanel({ perform, busy }: { perform: Perform; busy: boolean }) {
  const [config, setConfig] = useState<AppConfig | null>(null),
    [drafts, setDrafts] = useState<Record<string, string>>({}),
    [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      setConfig(await api<AppConfig>("/config"));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  if (!config)
    return error ? <p className="inline-error">{error}</p> : null;
  async function save(groupId: string, values: Record<string, string>) {
    const ok = await perform(
      () => api("/config", { values }, "PUT"),
      "Saved. ClipBot uses the new keys right away.",
    );
    if (ok) {
      const names = new Set(
        config!.groups.find((g) => g.id === groupId)!.fields.map((f) => f.name),
      );
      setDrafts(Object.fromEntries(Object.entries(drafts).filter(([k]) => !names.has(k))));
      await load();
    }
  }
  return (
    <section className="keys-panel">
      <div className="section-heading">
        <div>
          <h2>
            <KeyRound size={16} /> Your keys
          </h2>
          <p>
            {config.editable
              ? "Paste each service's key here. They're kept in Windows Credential Manager, encrypted to your Windows account, never in a plain file."
              : "This ClipBot reads its keys from environment variables (.env or your server's settings), so they can't be changed here."}
          </p>
        </div>
      </div>
      <div className="keys-grid">
        {config.groups.map((group) => {
          const changed = Object.fromEntries(
            group.fields
              .filter((f) => drafts[f.name] !== undefined)
              .map((f) => [f.name, drafts[f.name]])
              // An empty secret box means "keep what's saved"; Remove clears it.
              .filter(([name, value]) => value !== "" || !group.fields.find((f) => f.name === name)!.secret),
          );
          return (
            <article className="panel key-card" key={group.id}>
              <h3>{group.title}</h3>
              <p>{group.about}</p>
              {group.link && (
                <a className="text-link" href={group.link} target="_blank" rel="noreferrer">
                  Open the page for these keys <ArrowUpRight size={13} />
                </a>
              )}
              {group.fields.map((field) => (
                <Field
                  key={field.name}
                  field={field}
                  draft={drafts[field.name]}
                  editable={config.editable}
                  onChange={(value) => setDrafts({ ...drafts, [field.name]: value })}
                  onRemove={() => void save(group.id, { [field.name]: "" })}
                />
              ))}
              {config.editable && (
                <button
                  type="button"
                  className="button"
                  disabled={busy || !Object.keys(changed).length}
                  onClick={() => void save(group.id, changed)}
                >
                  <Check size={15} /> Save {group.title} settings
                </button>
              )}
              {group.id === "youtube" && (
                <ConnectYouTube config={config} onConnected={() => void load()} />
              )}
            </article>
          );
        })}
      </div>
      <div className="info-note">
        <ShieldCheck size={17} />
        <span>
          Keys are sent only to their own service. ClipBot never shows a saved key again; to
          change one, paste the new key over it.
        </span>
      </div>
    </section>
  );
}

/** A nudge on the Overview until the essentials are set up. */
export function SetupBanner({ studio }: { studio: Studio }) {
  const configured = (id: string) => studio.integrations.find((i) => i.id === id)?.configured;
  if (studio.demo_mode || ((configured("opus") || configured("vizard")) && configured("youtube")))
    return null;
  return (
    <div className="setup-banner">
      <KeyRound size={17} />
      <span>
        <b>Finish setting up ClipBot.</b> Add a clipping engine key (OpusClip or Vizard) and
        connect YouTube.
      </span>
      <Link className="button small primary" href="/connections">
        Go to Connections <ArrowRight size={13} />
      </Link>
    </div>
  );
}
