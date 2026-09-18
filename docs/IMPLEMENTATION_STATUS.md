# Implementation status

## Free local review (default)

`LLM_PROVIDER=local` needs no OpenAI or Anthropic key and makes no AI API calls. It ranks transcripts using simple length/punctuation heuristics, extracts titles and captions directly from the transcript, and compares timestamps and repeated wording for duplicates. These scores are sorting aids, not AI judgments. It does not assess meaning, claims, safety, or video/audio quality. All local results wait in Reserve for your manual approval, even with autopilot enabled. AI usage cost is zero; Vizard/OpusClip processing still consumes their credits. Sample/demo records remain separate simulated fixtures.

Paid review is preserved for later: set `LLM_PROVIDER=openai` plus `OPENAI_API_KEY` and `LLM_MODEL`; or set `LLM_PROVIDER=anthropic` plus `ANTHROPIC_API_KEY` and `LLM_MODEL` (this option still needs OpenAI for embeddings). Restart API and worker after changing providers. Existing reviewed clips retain their original evaluation; changing modes applies to new evaluations.


Implemented: Python/Next.js monorepo, migration, seven-service Compose, authenticated responsive studio, source authorization CRUD, manual/video-RSS/YouTube/local-folder discovery, dual-engine providers, archived media, structured judging/metadata, embeddings, deduplication, SQL outbox/Celery retries/leases/reconciliation, scheduling/limits/kill switch, resumable YouTube publishing and analytics, Instagram Reel create/poll/publish, analytics normalization and conservative cohort-based routing. Six-step onboarding and explicit development fixtures run without paid calls.

Verified locally on 14 September 2026:

- 46 backend tests pass, including provider contract mocks, the complete sample pipeline, deduplication, limits, CSRF, session rotation, signed callback replay protection, interrupted YouTube uploads and publication reconciliation.
- Python lint passes; Next.js Webpack production build and TypeScript validation pass.
- The standalone frontend runs against FastAPI and the local worker. Browser checks cover all eight views, source creation/archival, in-dialog API errors, clip details/platform copy, search, mobile navigation and horizontal overflow. Desktop/mobile screenshots were visually inspected.
- Fresh SQLite upgrade, schema comparison and rollback pass across all 17 tables. Compose structure and PostgreSQL offline migration SQL pass validation.

External gates and remaining production work:

- Paid end-to-end validation requires your credentials and authorized video. No real provider or social account was called during development.
- Docker was absent on this host; container execution, PostgreSQL migrations and target deployment require validation there.
- TikTok personal-use Direct Post is explicitly blocked by its documented intended-use rule. Download and metadata handoff is supported.
- Drive/Dropbox folder OAuth connectors remain explicit unsupported interfaces; manual video URLs/local synced folders work.
- Instagram automatic insight collection needs an app-version/scopes contract check. Exported metrics can be attached manually. Environment token adapters do not implement a browser OAuth/token vault product.
- One live account per platform is exposed until per-account credentials are added. The schema supports multiple accounts.
- Advanced automatic hook/duration/posting-time experiments and campaign-level rules are not implemented. Evidence and basic learned provider/topic selection are implemented; further learning follows live MVP validation.
- Storage lifecycle/retention, indexed vector search, exact cost invoicing, audiovisual moderation and distributed edge throttling require deployment-specific work before high volume.

This is an implemented MVP with a functioning local workflow, not a claim of production validation without these live acceptance checks.
