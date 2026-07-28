# Retail OS

WhatsApp-native AI business OS for B2B wholesale distributors in emerging markets. Retailers place orders via WhatsApp text and voice notes. The AI extracts, confirms, and manages the full business lifecycle — orders, inventory, receivables, bookkeeping, and tax filing.

## How it works

Retailers message your WhatsApp number. The system receives the message via the WhatsApp Cloud API webhook, classifies intent, extracts order details (even from informal language like "neela Surf 2 dabba"), resolves product aliases, confirms the order back with the retailer, and kicks off downstream workflows for inventory and receivables.

## Tech stack

| Layer | Tool |
|---|---|
| API | FastAPI |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Orchestration | Temporal (self-hosted) |
| Cache / dedup | Redis |
| Database | PostgreSQL (asyncpg) |
| Transcription | OpenAI Whisper |
| WhatsApp | Meta WhatsApp Cloud API — Solution Partner (shared credit line, no third-party BSP) |
| Package manager | uv |
| Linting | Ruff |
| Types | mypy |
| Testing | pytest + pytest-asyncio |

## Project structure

```
retail-os/
├── app/
│   ├── main.py               # FastAPI entry
│   ├── worker.py             # Temporal worker entry
│   ├── activities/           # Temporal activities (I/O: DB, AI, WhatsApp)
│   ├── agents/               # AI layer (prompts → LLM → parsed response)
│   ├── api/                  # Routers — validate + delegate only
│   ├── clients/              # External API clients (WhatsApp, LLM, Whisper)
│   ├── core/                 # Config, logging, DB, exceptions
│   ├── domain/               # Pure business logic (no I/O)
│   ├── models/               # SQLAlchemy models
│   ├── repositories/         # DB queries only
│   ├── schemas/              # Pydantic request/response models
│   ├── services/             # Thin orchestration between api/ and workflows —
│   │                         # starts/awaits Temporal workflows, translates
│   │                         # Temporal errors into AppError. No business logic;
│   │                         # exists because domain/ can't import Temporal and
│   │                         # routers must stay thin (validate + delegate only)
│   └── workflows/            # Temporal workflows (orchestration only)
└── tests/
    ├── unit/                 # Domain logic — no mocks, fast
    ├── integration/          # Activities + real DB + mocked clients
    └── workflow/             # Workflows via Temporal test environment
```

## Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)
- Docker (for Postgres, Redis, Temporal)
- A Meta WhatsApp Business Account with Cloud API access

## Setup

```bash
# 1. Clone and install
git clone <repo>
cd retail-os
make setup

# 2. Copy env and fill in secrets
cp .env.example .env

# 3. Start infrastructure
make docker-up

# 4. Apply DB migrations
make migrate

# 5. Run the API server and Temporal worker (separate terminals)
make run
make worker
```

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | Yes | Reserved for future JWT signing (admin dashboard auth) — not yet used by any code |
| `PIN_ENCRYPTION_KEY` | Yes | Derives the key that encrypts stored WhatsApp two-step PINs at rest (`app/core/security.py`); deliberately separate from `SECRET_KEY` |
| `DATABASE_URL` | Yes | Must use `postgresql+asyncpg://` |
| `WHATSAPP_API_VERSION` | No | Defaults to `v25.0` — Graph API versions sunset ~2 years after release, bump periodically |
| `WHATSAPP_APP_ID` | Yes | Meta App ID (platform-level) |
| `WHATSAPP_APP_SECRET` | Yes | Meta App Secret; also verifies webhook `X-Hub-Signature-256` |
| `WHATSAPP_SYSTEM_USER_ID` | Yes | System User ID (Business Settings → System Users) |
| `WHATSAPP_SYSTEM_USER_TOKEN` | Yes | Non-expiring System User token used to send for all tenants. Generate it with `whatsapp_business_management`, `whatsapp_business_messaging`, and `whatsapp_business_manage_events` permissions — required for phone number registration and credit sharing |
| `WHATSAPP_WEBHOOK_SECRET` | Yes | `hub.verify_token` for the GET handshake only |
| `WHATSAPP_EXTENDED_CREDIT_ID` | Yes | Retail OS's extended credit line ID (Business Manager → Extended Credits) — shared with each tenant's WABA so distributors never add their own payment method |
| `WHATSAPP_TEST_RECIPIENT_NUMBER` | No | A WhatsApp number you control; if set, a smoke-test message is sent after each successful onboarding |
| `REDIS_URL` | No | Defaults to `redis://localhost:6379` |
| `TEMPORAL_HOST` | No | Defaults to `localhost:7233` |
| `RECONCILIATION_INTERVAL_MINUTES` | No | Defaults to `60` — how often `TenantReconciliationWorkflow` retries failed credit-share/phone-registration steps |
| `ENVIRONMENT` | No | `development` / `staging` / `production` |

## WhatsApp webhook setup

The webhook endpoint is `POST /api/v1/webhooks/whatsapp`. Meta also sends a `GET` request on first registration to verify the endpoint — the handler echoes back the `hub.challenge` parameter.

In Meta Business Manager, set your callback URL to `https://your-domain/api/v1/webhooks/whatsapp` and subscribe to the `messages` field.

## Tenant onboarding (Embedded Signup)

Distributors connect their own WhatsApp Business Account via Meta's Embedded Signup popup (frontend, not in this repo) and POST the result to `POST /api/v1/auth/whatsapp/callback`. `TenantOnboardingWorkflow` exchanges the code, selects/records the WABA, shares Retail OS's Solution Partner credit line, registers the primary phone number for Cloud API use, and upserts the tenant. A tenant can end up in one of three `onboarding_status` states: `complete`, `waba_only` (customer didn't pick a number yet), or `phone_unregistered` (number chosen but Cloud API registration failed) — see `docs/whatsapp-embedded-signup-v4-audit.md` for the full flow and Meta references.

Credit sharing and phone registration are allowed to fail non-fatally during onboarding (a tenant still gets registered either way). `TenantReconciliationWorkflow` runs on a recurring Temporal Schedule (`RECONCILIATION_INTERVAL_MINUTES`, created automatically by `app/worker.py` on startup) and retries both using the platform System User token — the tenant's original short-lived Embedded Signup token isn't needed for retries, and isn't kept around after onboarding anyway.

## Development commands

```bash
make run           # Start API server (port 8000)
make worker        # Start Temporal worker
make lint          # Ruff fix
make format        # Ruff format
make check         # CI mode (no fixes)
make typecheck     # mypy
make test          # All tests
make test-unit     # Unit tests only
make migrate       # Apply migrations
make migrate-new msg="add orders table"
make docker-up     # Start Postgres, Redis, Temporal
make docker-down   # Stop services
```

API docs are available at `http://localhost:8000/swagger-ui` when running locally.

## Architecture rules

- `domain/` is pure Python — no SQLAlchemy, no HTTP, no Temporal, no FastAPI
- `workflows/` only calls `activities/` — no I/O directly
- `activities/` owns all external I/O (DB, AI, WhatsApp)
- `api/` validates and delegates — to `domain/`, `schemas/`, or `services/` (never straight to Temporal or a repository)
- `services/` starts/awaits Temporal workflows and translates their errors for `api/` — no business logic, no direct DB/HTTP calls of its own
- `core/` is imported by everyone and imports nothing from the app

## Current phase

Tenant onboarding (Embedded Signup, Solution Partner credit sharing, phone number registration, reconciliation retries) is built — see [Tenant onboarding](#tenant-onboarding-embedded-signup) above.

**Phase 1 — Order Capture** (in progress)

- [x] WhatsApp webhook ingestion
- [ ] Message classification (intent detection)
- [ ] Order extraction from text
- [ ] Product alias resolution
- [ ] Order confirmation flow
- [ ] Admin dashboard (orders view)

Future phases will add voice note transcription, inventory management, receivables tracking, bookkeeping, and tax filing.
