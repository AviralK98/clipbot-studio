# OpusClip integration

Official documentation checked 14 September 2026:
- [Create project](https://help.opus.pro/api-reference/endpoints/create-project)
- [Get clips](https://help.opus.pro/api-reference/endpoints/get-clips)
- [Clip schema](https://help.opus.pro/api-reference/schemas/clip-representation)
- [Signed webhooks](https://help.opus.pro/api-reference/webhook)
- [Limits](https://help.opus.pro/api-reference/limitation)

Base URL: https://api.opus.pro/api. Authentication: Authorization: Bearer OPUS_API_KEY. x-opus-org-id selects an organization. POST /clip-projects sets videoUrl, uploadedVideoAttr.title, curationPref.model/clipDurations and renderPref.layoutAspectRatio=portrait. ClipBasic is the default; ClipAnything can be selected in OPUS_MODEL. A success conclusion callback is registered when PUBLIC_API_BASE_URL is configured.

GET /exportable-clips?q=findByProjectId&projectId=... returns candidates. The adapter paginates pageNum/pageSize, normalizes durationMs, text, uriForExport and identifiers, and archives media. Standard core rate limit is thirty requests per minute. 429s back off via durable jobs.

The public docs verified here do not establish a project-status GET endpoint. get_status therefore reports awaiting_webhook; ClipBot does not invent a status API or treat a partial clips list as complete. A valid signed success callback or the explicit dashboard completion-confirmation action releases import. A twelve-hour wait becomes an actionable blocked job.

Webhook validation uses HMAC-SHA256(secret, raw_body + salt), constant-time comparison and a five-minute freshness check. Salts are persisted to reject replays because the timestamp is not signed. The body's projectId or id must match the stored external project. The exact success payload must be checked against a live callback; unrecognized payloads are rejected, never guessed.

The timeRanges field is described as seconds but the example uses values consistent with milliseconds. OPUS_TIME_RANGE_UNIT=unknown therefore preserves no normalized ranges, leaving transcript and embedding deduplication active. Set milliseconds or seconds only after validating a real response against the source video. Do not infer units from magnitude.

No provider-side idempotency contract was established. An ambiguous submission is held for reconciliation. The integration does not bypass content ownership checks or API plan requirements.

## Export retrieval

Clip lists may be a bare array or a `{data: [...], total: N}` envelope. When `uriForExport` is absent, ClipBot collects existing clip IDs into a named export collection and calls `POST /collections/{id}/export`. Collection ID and membership progress are checkpointed in the provider project, and memberships are checked before adding on retry. Export links are archived through the normal media pipeline. If the export endpoint returns an empty link but an authorized MP4 preview is available, ClipBot archives the unmodified preview, records media_variant=opus_preview, labels it in the review reason and requires manual approval. Branding and quality may differ from a full export. No new clipping project is submitted. Existing imported clips receive recovered URLs and blocked evaluation jobs are requeued.

Reference: https://github.com/opus-pro/opus-skills/blob/main/skills/opusclip/references/api-reference.md
