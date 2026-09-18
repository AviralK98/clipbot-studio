# Deployment

Run docker compose up -d --build, docker compose ps, and docker compose logs --tail 100 backend worker scheduler. Services include frontend, backend, PostgreSQL, Redis, Celery worker, Beat and n8n. Host ports bind only to loopback. Backend/frontend containers use non-root accounts. Replace n8n's stable image tag with a tested release digest for controlled rollouts.

Docker was not installed on this build host. Container execution and PostgreSQL integration require target-host validation; local SQLite execution and the frontend production build are tested separately. A generated Compose file is not a live deployment.

Set APP_ENV=production, a unique ADMIN_PASSWORD of at least sixteen characters, random SESSION_SECRET of at least thirty-two characters, strong POSTGRES_PASSWORD, HTTPS WEB_ORIGIN and DEMO_MODE=false. Changing ADMIN_PASSWORD and restarting invalidates prior sessions. Configure API_TOKEN for trusted ingress. Keep n8n private; configure its own owner and enable secure cookies if exposed over HTTPS.

Place a TLS proxy before the frontend and expose the signed Opus webhook route as needed. Serve PUBLIC_MEDIA_BASE_URL through a media-only origin containing intended video assets, never the database or full filesystem. Block private/metadata network egress. Persist PostgreSQL, Redis AOF and media volumes; rehearse backup restores and monitor backlog, spend, disk space, blocked jobs and dead letters. Global storage retention/quotas are deployment work; the current adapter bounds individual downloads.

Live acceptance: run one authorized video with low limits; compare provider usage and timing, validate Opus's actual signed callback schema, inspect both outputs, review metadata, upload privately to YouTube, retrieve metrics, exercise the posting stop and recover an interrupted upload. Complete platform review before public output. Real credentials, paid account access and a Docker host are external prerequisites.
