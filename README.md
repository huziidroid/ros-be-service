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
| WhatsApp | Meta WhatsApp Cloud API (direct) |
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
| `SECRET_KEY` | Yes | JWT signing secret |
| `DATABASE_URL` | Yes | Must use `postgresql+asyncpg://` |
| `WHATSAPP_ACCESS_TOKEN` | Yes | Meta permanent or system user token |
| `WHATSAPP_PHONE_NUMBER_ID` | Yes | From Meta Business Manager |
| `WHATSAPP_WEBHOOK_SECRET` | Yes | Used to verify webhook payloads |
| `REDIS_URL` | No | Defaults to `redis://localhost:6379` |
| `TEMPORAL_HOST` | No | Defaults to `localhost:7233` |
| `ENVIRONMENT` | No | `development` / `staging` / `production` |

## WhatsApp webhook setup

The webhook endpoint is `POST /api/v1/webhooks/whatsapp`. Meta also sends a `GET` request on first registration to verify the endpoint — the handler echoes back the `hub.challenge` parameter.

In Meta Business Manager, set your callback URL to `https://your-domain/api/v1/webhooks/whatsapp` and subscribe to the `messages` field.

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
- `api/` validates and delegates — no business logic
- `core/` is imported by everyone and imports nothing from the app

## Current phase

**Phase 1 — Order Capture** (in progress)

- [x] WhatsApp webhook ingestion
- [ ] Message classification (intent detection)
- [ ] Order extraction from text
- [ ] Product alias resolution
- [ ] Order confirmation flow
- [ ] Admin dashboard (orders view)

Future phases will add voice note transcription, inventory management, receivables tracking, bookkeeping, and tax filing.
