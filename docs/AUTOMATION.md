# Automation and resilience

Celery with Redis delivers work. SystemJob in SQL is the durable outbox; HTTP requests commit intent before a worker touches paid APIs. Beat dispatches every fifteen seconds and source discovery is scheduled hourly. Source/video, provider/video, candidate/provider, post/account and analytics/checkpoint constraints prevent duplicate work.

A transaction serializes scheduler reservations and claims (PostgreSQL row lock or SQLite BEGIN IMMEDIATE). Workers lease jobs for thirty minutes, with a twenty-five-minute task limit. Expired leases resume from persisted provider/media/upload checkpoints. Deferrals do not consume failure attempts. Transient errors retry with exponential backoff and jitter; exhaustion moves the job to dead_letter. Missing credentials and budget limits become blocked. Ambiguous non-idempotent external requests become needs_reconciliation.

The SQL outbox survives broker outages. Redis should use AOF persistence. Two dispatch deliveries may race, but only one can claim a job. Worker network timeouts are bounded. Project completion waits for both engines before deduplication and scheduling; a blocked engine remains visible while successful engine candidates can still be inspected. Ops must resolve blocked projects before final automatic selection.

Source adapters: manual URLs; YouTube channel/playlist through the official Data API (up to 500 recent items per scan); RSS video enclosures with duration metadata; local MP4 folders via FFprobe and public media delivery. Drive and Dropbox folder connectors report an explicit unsupported capability; their video URLs can be submitted manually.

## n8n

Import automation/source-video.json. Configure Header Auth credentials on both the incoming webhook and HTTP request. The backend credential header is X-API-Key with API_TOKEN from .env. The event body is {source_id, title, url, duration}; authorization is still validated by FastAPI. Workflows do not own ranking, budgets or publishing decisions. n8n is optional; the core scheduler runs without it.

## Kill switches

AUTOPILOT=false initially means manual approval. The persisted dashboard switch controls subsequent execution. STOP_ALL_POSTING=true in the environment is an additional hard stop. The dashboard Stop all posting setting is checked immediately before publishing work and between resumable steps. A request already transmitted to a platform cannot reliably be recalled. Source revocation and account disabling are checked again at publish time.
