# Troubleshooting

- Backend unavailable: start the API on :8000 or configure frontend BACKEND_URL. Check /health and /ready. Worker and API must share the same database and .env.
- Login rejected: use ADMIN_PASSWORD and ensure WEB_ORIGIN exactly matches the browser, including port. localhost and 127.0.0.1 are different origins. Restart after .env edits.
- Worker not detected: start python -m clipbot.local_worker locally, or inspect Compose worker/scheduler logs. The scheduler writes the heartbeat.
- Missing credential: set the variable named by the blocked job, restart backend/worker, then retry in Queue. Live jobs never switch to mocks.
- Daily budget exhausted: review configured limits or retry after the UTC day resets. Ambiguous reservations remain conservatively charged.
- Opus waiting: configure public callback origin/signing key; verify the signed payload identifies the stored external project. Alternatively, confirm completion in Queue after viewing the provider dashboard. A partial clips response is not proof of completion.
- Provider submission reconciliation: locate the existing project using the ClipBot ID appended to its title, then attach its external ID. Never resubmit blindly after a lost response.
- Publication reconciliation: check the platform account and upload journal. Use Queue → Record published post to attach the verified remote publication ID and its actual publication time; do not clear a non-idempotent journal without confirming state.
- YouTube private output: private is the default and unaudited API projects may also be restricted. Complete the appropriate review and set YOUTUBE_PRIVACY deliberately.
- Instagram failed fetch: the public media origin must serve the persisted MP4. Dashboard media routes require auth. Verify professional account eligibility and Page-token expiry.
- TikTok blocked: Direct Post excludes this personal-use workflow. Download the clip and use its generated metadata to publish manually.
- Missing metrics: null means unavailable. Owner reports need scopes and time to populate. Attach real exported snapshots; manual metrics do not drive strategy.
- Candidates analyzing: inspect evaluate jobs; final selection waits for both engines, scoring and embeddings. Missing transcripts are rejected.
- Migration drift: inspect alembic current/history, back up data, review the migration and apply it. Do not delete production data to bypass a migration issue.

- Frontend builds use Next.js’s supported Webpack mode. This avoids a Turbopack persistent-cache failure observed on the Windows host. Stop the development server before installing frontend dependencies.
