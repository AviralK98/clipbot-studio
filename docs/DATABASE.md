# Database and ER diagram

SQLAlchemy 2 models use portable UUID strings, JSON, booleans and UTC timestamps. API dates end in Z. PostgreSQL is for production; SQLite enables foreign keys, WAL and BEGIN IMMEDIATE. Seventeen tables cover the single-owner studio.

~~~mermaid
erDiagram
 sources ||--o{ source_videos : owns
 source_videos ||--o{ provider_projects : processes
 provider_projects ||--o{ clips : generates
 clips ||--o| clip_scores : evaluates
 clips ||--o| clip_embeddings : represents
 clips ||--o{ scheduled_posts : schedules
 social_accounts ||--o{ scheduled_posts : targets
 scheduled_posts ||--o| published_posts : completes
 published_posts ||--o{ analytics_snapshots : measures
 source_videos ||--o{ api_usage : reserves
 clips }o--o| clips : duplicate_of
 analytics_snapshots }o..o{ strategy_metrics : aggregates
 analytics_snapshots }o..o{ provider_metrics : compares
 strategy_metrics }o..o{ ai_insights : explains
 system_state ||..o{ system_jobs : controls
~~~

Users store the initial owner's password hash. Jobs carry handler-specific record IDs in payloads. Source deletion archives the source, preserving authorization history. Unique constraints protect source+video, video+provider, project+clip, clip+account, scheduled-post+publication and publication+checkpoint. Jobs and usage reservations each have an idempotency key.

Initial schema is frozen in apps/backend/migrations/versions. Apply with alembic upgrade head. For changes, generate and review alembic revision --autogenerate -m description against an up-to-date development database. Never edit applied revisions. Test SQLite batch DDL and PostgreSQL upgrades against a backup. Production startup requires migrations and never creates tables implicitly. Back up database and media together. Provider secrets are environment references; internal upload-session URLs are excluded from API responses.
