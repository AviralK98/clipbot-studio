"use client";
import { useState } from "react";
import { api, Studio } from "@/lib/types";
export function BulkActions({
  studio,
  provider,
  query,
  refresh,
}: {
  studio: Studio;
  provider: string;
  query: string;
  refresh: () => Promise<void>;
}) {
  const [account, setAccount] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [confirmation, setConfirmation] = useState<{
    action: string;
    ids: string[];
    privacy: string;
  } | null>(null);
  const accounts = studio.accounts.filter(
    (a) => a.enabled && a.demo === studio.demo_mode,
  );
  async function prepare(action: string) {
    setBusy(true);
    setMessage("");
    try {
      const p = await api<{
        approve: string[];
        upload: string[];
        privacy: string;
      }>(
        `/clips/bulk-preview?provider=${encodeURIComponent(provider)}&q=${encodeURIComponent(query)}`,
      );
      const ids = action === "approve" ? p.approve : p.upload;
      if (!ids.length) {
        setMessage(
          action === "approve"
            ? "No eligible clips to approve."
            : "Approve clips before uploading.",
        );
        return;
      }
      if (ids.length > 500) {
        setMessage("Narrow the search to 500 clips or fewer.");
        return;
      }
      setConfirmation({ action, ids, privacy: p.privacy });
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function submit() {
    if (!confirmation) return;
    setBusy(true);
    try {
      const result = await api<{
        changed: string[];
        skipped: { id: string; reason: string }[];
      }>(`/clips/bulk-${confirmation.action}`, {
        clip_ids: confirmation.ids,
        account_id: account || null,
      });
      setMessage(
        `${result.changed.length} ${confirmation.action === "approve" ? "approved" : "queued to upload now"}. ${result.skipped.length} skipped. ${Array.from(new Set(result.skipped.map((s) => s.reason))).join("; ")}`,
      );
      setConfirmation(null);
      await refresh();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel" style={{ padding: 16, marginBottom: 16 }}>
      <div
        style={{
          display: "flex",
          gap: 12,
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        <button
          className="button"
          disabled={busy}
          onClick={() => void prepare("approve")}
        >
          Approve all
        </button>
        <select
          aria-label="Bulk upload destination"
          value={account}
          onChange={(e) => {
            setAccount(e.target.value);
            setConfirmation(null);
          }}
        >
          <option value="">Choose upload destination</option>
          {accounts.map((a) => (
            <option value={a.id} key={a.id}>
              {a.name} · {a.platform}
            </option>
          ))}
        </select>
        <button
          className="button primary"
          disabled={busy || !account || studio.settings.stop_all_posting}
          onClick={() => void prepare("upload")}
        >
          Upload all now
        </button>
      </div>
      <p className="form-hint">
        Applies across all pages matching your search and engine, regardless of
        status tab. Flagged clips need individual review. Uploads start as the
        worker processes them; daily limits still apply.
      </p>
      {studio.settings.stop_all_posting && (
        <p className="form-hint">
          Posting is paused. Resume it in Queue to upload.
        </p>
      )}
      {confirmation && (
        <div role="region" aria-label="Confirm bulk action">
          <p>
            {confirmation.action === "approve"
              ? `Approve ${confirmation.ids.length} clips? This records your manual approval, including any Opus preview branding.`
              : `Upload ${confirmation.ids.length} approved clips to ${accounts.find((a) => a.id === account)?.name}? YouTube privacy: ${confirmation.privacy}. This skips scheduled time slots and spacing. Clips above daily limits remain approved.`}
          </p>
          <button
            className="button primary"
            disabled={busy}
            onClick={() => void submit()}
          >
            {busy
              ? "Working…"
              : confirmation.action === "approve"
                ? "Confirm approval"
                : "Start uploads now"}
          </button>
          <button
            className="button"
            disabled={busy}
            onClick={() => setConfirmation(null)}
          >
            Cancel
          </button>
        </div>
      )}
      {message && <p role="status">{message}</p>}
    </section>
  );
}
