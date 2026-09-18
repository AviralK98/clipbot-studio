# ClipBot

An autonomous studio for authorized long-form content: dual clipping engines, structured AI review, deduplication, scheduling, publishing and measured feedback. Python 3.12 / FastAPI / SQLAlchemy + Next.js / TypeScript. ClipBot is an independent repository containing its own backend, frontend, workers and deployment configuration.

## Start with Docker

1. Clone this repository and enter its root directory.
2. Copy .env.example to .env (PowerShell: Copy-Item .env.example .env).
3. Set ADMIN_PASSWORD and SESSION_SECRET. For local exploration, set DEMO_MODE=true.
4. Run docker compose up -d --build.
5. Open http://localhost:3000 and sign in with ADMIN_PASSWORD. The local default is clipbot-local.
6. In development mode, click Load sample workflow. All sample clips, accounts, scores and analytics are explicitly marked. The worker processes a new sample video through the same pipeline without paid API calls.

Services: frontend :3000, backend :8000, PostgreSQL, Redis, Celery worker, Celery Beat scheduler, n8n :5678. All exposed ports bind to loopback. No credentials are bundled.

## Local development without Docker

Use Python 3.12+ and Node 22+. From this folder:

    python -m venv .venv
    .venv\Scripts\python.exe -m pip install -e ".[dev]"
    Copy-Item .env.example .env
    .venv\Scripts\python.exe -m alembic upgrade head
    cd apps/frontend
    npm ci
    cd ../..

Run three terminals:

    powershell -File scripts/local.ps1 backend
    powershell -File scripts/local.ps1 worker
    powershell -File scripts/local.ps1 frontend

On macOS/Linux, activate .venv and run uvicorn clipbot.api:app, python -m clipbot.local_worker, and npm run dev in apps/frontend. SQLite is used by default. Redis is unnecessary for this local runner; Compose uses Celery/Redis and PostgreSQL.

## Connect real services

Set DEMO_MODE=false for live operation. Follow the dashboard setup wizard and docs/SETUP.md. Store secrets in .env, then restart backend and worker. Configure VIZARD_API_KEY, OPUS_API_KEY, OPUS_WEBHOOK_SECRET, PUBLIC_API_BASE_URL and YOUTUBE_DATA_API_KEY. Free local review is the default; OpenAI/Anthropic keys are optional for paid AI review later. YouTube publishing needs its OAuth client and refresh token. Instagram uses Facebook Login / Page-token credentials. Accounts are registered in Connections after credentials are configured.

TikTok Direct Post explicitly excludes private tools that post only to their owner's accounts. ClipBot provides a download-and-metadata handoff; it does not bypass that restriction. Drive/Dropbox folder OAuth and Instagram automated insights are currently explicit capability gaps. See docs/SOCIAL_APIS.md and docs/IMPLEMENTATION_STATUS.md.

Live provider contracts are implemented from official documentation and exercised with mocked contract tests. A real paid end-to-end validation still requires your keys and an authorized video. ClipBot never substitutes demo output when a live integration is unconfigured.

## Verification

    .venv\Scripts\python.exe -m pytest -q
    .venv\Scripts\python.exe -m ruff check apps/backend tests
    cd apps/frontend
    npm run typecheck
    npm run build

For the built local dashboard, run npm run build and npm run preview from apps/frontend; keep the backend and local worker running in their terminals. The preview binds to 127.0.0.1.

Deployment checks: .venv\Scripts\python.exe scripts/verify_deployment.py validates the Compose structure, a fresh SQLite upgrade/rollback, and offline PostgreSQL migration SQL. It does not start Docker or a PostgreSQL server.

## Documentation

- docs/ARCHITECTURE.md — components, diagram and exact MVP
- docs/SETUP.md — onboarding and credential variables
- docs/VIZARD.md / OPUS.md — verified contracts and limitations
- docs/SOCIAL_APIS.md — publishing restrictions and account setup
- docs/DATABASE.md — ER diagram and migration workflow
- docs/AUTOMATION.md — queue, scheduler and n8n
- docs/AI_SCORING.md — rubric, duplicate logic and strategy
- docs/DEPLOYMENT.md / SECURITY.md — operating and hardening
- docs/TROUBLESHOOTING.md — failures and reconciliation
- docs/COSTS.md — transparent planning assumptions
- docs/IMPLEMENTATION_STATUS.md — verified behavior and remaining live gates
