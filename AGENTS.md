# ros-be-service

WhatsApp-native AI business OS for B2B wholesale distributors in emerging markets. Retailers place orders via WhatsApp text and voice notes; the system extracts, confirms, and manages the full business lifecycle — orders, inventory, receivables, bookkeeping, and tax filing.

## Tech stack

| Layer           | Tool                    |
| --------------- | ----------------------- |
| API             | FastAPI                 |
| ORM             | SQLAlchemy 2.0 (async)  |
| Migrations      | Alembic                 |
| Orchestration   | Temporal (self-hosted)  |
| Cache / dedup   | Redis                   |
| Database        | PostgreSQL (asyncpg)    |
| Transcription   | OpenAI Whisper          |
| WhatsApp        | Meta WhatsApp Cloud API |
| Package manager | uv                      |
| Linting         | Ruff                    |
| Types           | mypy (strict)           |
| Testing         | pytest + pytest-asyncio |

## Project structure

```
ros-be-service/
├── app/
│   ├── main.py          # FastAPI entry
│   ├── worker.py         # Temporal worker entry
│   ├── activities/       # Temporal activities (I/O: DB, AI, WhatsApp)
│   ├── agents/            # AI layer (prompts -> LLM -> parsed response)
│   ├── api/               # Routers - validate + delegate only
│   ├── clients/           # External API clients (WhatsApp, LLM, Whisper)
│   ├── core/               # Config, logging, DB, exceptions
│   ├── domain/             # Pure business logic (no I/O)
│   ├── models/             # SQLAlchemy models
│   ├── repositories/       # DB queries only
│   ├── schemas/            # Pydantic request/response models
│   ├── services/           # Thin orchestration between api/ and workflows -
│   │                       # starts/awaits Temporal workflows, translates
│   │                       # Temporal errors into AppError. No business logic;
│   │                       # exists because domain/ can't import Temporal and
│   │                       # routers must stay thin (validate + delegate only)
│   └── workflows/          # Temporal workflows (orchestration only)
├── alembic/                # DB migrations
└── tests/
    ├── unit/                # Domain logic - no mocks, fast
    ├── integration/          # Activities + real DB + mocked clients
    └── workflow/             # Workflows via Temporal test environment
```

Respect the layering above when adding code: routers stay thin, business logic lives in `domain/`, DB access only through `repositories/`, and Temporal is only touched from `activities/`, `services/`, and `workflows/`.

## Commands

Run via `make` from this directory (wraps `uv run` internally):

```
make setup           # install deps + pre-commit hooks (first time)
make run              # start FastAPI server (reload, port 8000)
make worker            # start Temporal worker
make docker-up          # start Postgres, Redis, Temporal via docker compose
make migrate             # apply pending Alembic migrations
make migrate-new msg="..." # create a new migration
make lint                # ruff check --fix
make format               # ruff format
make check                # ruff check + format --check + mypy (CI mode)
make test                 # full pytest suite
make test-unit             # unit tests only
```

## Conventions

- Ruff handles linting, formatting, and import sorting (line length 88, double quotes).
- mypy runs in strict mode against `app/` (excludes `alembic/` and `tests/`).
- Tests are split by layer (`unit`, `integration`, `workflow`) matching the structure above — keep new tests in the matching directory.
