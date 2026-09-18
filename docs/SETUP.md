# Setup and credentials

## Free local review (default)

`LLM_PROVIDER=local` needs no OpenAI or Anthropic key and makes no AI API calls. It ranks transcripts using simple length/punctuation heuristics, extracts titles and captions directly from the transcript, and compares timestamps and repeated wording for duplicates. These scores are sorting aids, not AI judgments. It does not assess meaning, claims, safety, or video/audio quality. All local results wait in Reserve for your manual approval, even with autopilot enabled. AI usage cost is zero; Vizard/OpusClip processing still consumes their credits. Sample/demo records remain separate simulated fixtures.

Paid review is preserved for later: set `LLM_PROVIDER=openai` plus `OPENAI_API_KEY` and `LLM_MODEL`; or set `LLM_PROVIDER=anthropic` plus `ANTHROPIC_API_KEY` and `LLM_MODEL` (this option still needs OpenAI for embeddings). Restart API and worker after changing providers. Existing reviewed clips retain their original evaluation; changing modes applies to new evaluations.


Run the commands in README.md. The local dashboard is http://localhost:3000, with ADMIN_PASSWORD from .env. Run migrations before starting a new deployment. SQLite is for local development; Compose uses PostgreSQL. The six-step wizard shows configuration state without accepting or revealing secrets in the browser.

## First real video

1. Set DEMO_MODE=false and restart backend and worker. Use a fresh DATABASE_URL for a clean live studio, then create live sources and destinations. Sample records stay simulated and cannot call live adapters. Configure VIZARD_API_KEY and OPUS_API_KEY. OPUS_ORG_ID selects the organization when required. Confirm prepaid credits/API access in each provider dashboard.
2. Set PUBLIC_API_BASE_URL to an HTTPS address routed to ClipBot. Set OPUS_WEBHOOK_SECRET to your organization's first API secret. Opus completion callbacks use /api/webhooks/opus/{local_project_id}; the callback URL is included in the project submission. The callback signature is validated and the signed payload must identify the stored external project. Confirm the actual callback payload in a live acceptance test. Without public callbacks, use Queue → Confirm completed project after checking the provider dashboard.
3. Keep LLM_PROVIDER=local for free transcript review with manual approval. OpenAI and Anthropic credentials are optional; see the paid-review instructions above.
4. Configure YOUTUBE_DATA_API_KEY for source discovery and authoritative YouTube duration checks. This is independent of publishing OAuth.
5. Add an authorized source. Choose owner, licensed, or permission; record the permission and allowed platforms. Submit the authorized video and full duration. Both engines run when routing is dual.
6. Add publishing credentials (below), then register a destination in Connections. Inspect the ranked candidates and schedule one clip.
7. Verify paid usage and published output with a small batch before enabling continuous live operation.

## YouTube OAuth

Create a Google Cloud project, enable the YouTube Data and Analytics APIs, configure a consent screen and OAuth client, and obtain a refresh token using Google's supported OAuth flow. Request youtube.upload for uploads, youtube.readonly for account data and yt-analytics.readonly for owner analytics. Store YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN in .env. Tokens are never sent to the browser or saved in repository files. The refresh exchange happens server-side before API calls. Testing-mode token lifetime and quota/audit requirements are account dependent; inspect the Cloud console. YOUTUBE_PRIVACY defaults to private. Set public only after checking your project is eligible.

## Instagram

The implemented adapter uses Facebook Login and a Page access token. Link a professional Instagram account to a Facebook Page. Set INSTAGRAM_ACCESS_TOKEN to the appropriately scoped Page token and INSTAGRAM_USER_ID to the linked professional account ID. Set INSTAGRAM_API_VERSION to a supported version verified for your app and PUBLIC_MEDIA_BASE_URL to a public HTTPS media origin. The public origin must serve the persistent archived video URLs through object storage or a media-only reverse proxy. Dashboard media routes remain authenticated. Token renewal must be handled through your approved Meta app flow; expired credentials become blocked jobs.

## Local folder delivery

Local folders are relative to SOURCE_DIRECTORY. FFprobe verifies file duration; Docker includes it. Complete files are copied to persistent media storage. The public media origin must make the generated sources/{hash}.mp4 and clips/{uuid}.mp4 keys reachable by the provider. Do not expose the entire backend or filesystem to implement this.

Environment changes require restarting backend and worker. Runtime posting times, thresholds and kill switches are persisted and edited in Settings. Existing database settings take precedence over initial AUTOPILOT defaults; STOP_ALL_POSTING=true in the environment is an additional hard stop.

## Bulk clip actions

Clips has Approve all and Upload all now. Both use all pages matching the current search and engine, independent of the status tab. Approval skips flagged, incomplete, rejected and duplicate clips. Upload requires an approved clip and a selected destination and records one durable job per clip/account. It bypasses scheduled slots and minimum spacing only, preserves daily account/platform/global caps and the posting stop, and reports skipped clips with reasons. Existing queued/published/cancelled records are not recreated. Confirmation shows the batch count and YouTube privacy. These buttons do not run until explicitly confirmed.
