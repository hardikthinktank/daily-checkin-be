# Daily Check-In Backend

FastAPI backend for the daily check-in care-management loop: a patient answers
three questions a day, a rule engine decides what happens next, a care manager
works the results, and the physician gets a monthly picture.

> Every threshold in the seeded rules is a demo placeholder (see the
> `threshold_source` field on `GET /admin/rules`). None of it is clinically
> validated -- see [Known limitations / open items](#known-limitations--open-items)
> before any of this touches a real patient.

## Architecture

```
app/
  domain/            Pure Python, zero I/O. No SQLAlchemy or FastAPI imports
    scoring.py          D3 score, usual score (median of last 14), change
    rules/
      types.py            Plain dataclasses: RuleDefinition, RuleFiring, CheckinContext...
      strategies.py        One function per rule *shape* (threshold_gte, streak_gte, ...)
      engine.py            evaluate(context, rule_table) -> list[RuleFiring]
      failsafes.py          The two rules that can never be switched off (spec section 7)
      flags.py              Repeat-firing reconciliation (72h dedup, never lower a level)
      seed_data.py           The ten rules D3-01..D3-10, as plain data

  db/                 SQLAlchemy models + Alembic migrations (Postgres-only:
                      JSONB, partial unique index, and the T13 trigger all
                      rely on it)

  services/           The only layer that touches both the DB and app.domain
    checkin_service.py    Submission orchestration: idempotency, versioning,
                            scoring, engine, reconciliation, persistence
    flag_service.py        Work list, "why it fired", the four actions
    admin_list_service.py  Spec section 9
    summary_service.py     Spec section 10, with a cache table
    rule_admin_service.py  Versioned rule CRUD
    context_builder.py     Translates ORM rows -> domain dataclasses (the
                            ONLY place that boundary crossing happens)
    flag_apply.py           Shared Flag/FlagEvent write logic (submission
                            path and the R9 timer job both use this)

  api/                FastAPI routers, Pydantic schemas, error handling
  jobs/               R9 (no-checkin timer) + monthly summary pre-build,
                      wired into an in-process APScheduler
scripts/              seed_rules.py, seed_demo_data.py
tests/
  domain/             T1-T10, T12 (and extras) -- no DB, no app, pure functions
  api/                T11, T13, T14, T15 + full HTTP flows, against a real
                      Postgres test database
```

The domain/service split is deliberate: the spec requires the rule engine to
be testable "on its own, with no screens and no database" (section 11). The
`app/domain/` package is that engine; everything else is an adapter around it.

## Prerequisites

- **Python 3.11+**
- **PostgreSQL 14+** (the project uses JSONB, partial unique indexes, and a
  custom trigger — SQLite is used only for the domain-layer tests)

---

## Setup

### 1. Clone the repository

```bash
git clone <repository-url>
cd daily-checkin-backend
```

### 2. Create Postgres databases

Two databases are needed: one for development, one for the test suite.

```sql
CREATE DATABASE care_management;
CREATE DATABASE care_management_test;
```

### 3. Create a Python virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
```

### 4. Install dependencies

**Option A — using `requirements.txt` (quickest):**

```bash
pip install -r requirements.txt
```

**Option B — editable install from `pyproject.toml` (recommended for development):**

```bash
pip install -e ".[dev]"
```

Both options install all core and dev/test dependencies.

### 5. Configure environment variables

Copy `.env.example` to `.env` and fill in your Postgres credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```env
CHECKIN_DATABASE_URL=postgresql+asyncpg://<user>:<pass>@localhost:5432/care_management
```

All settings are `CHECKIN_`-prefixed env vars; see `app/config.py` for the
full list.

### 6. Run database migrations

Apply migrations to the **dev** database:

```bash
alembic upgrade head
```

Apply migrations to the **test** database (required before running the API
test suite):

```bash
CHECKIN_DATABASE_URL=postgresql+asyncpg://<user>:<pass>@localhost:5432/care_management_test \
  alembic upgrade head
```

### 7. Seed data

```bash
# The 10 clinical rules D3-01..D3-10 (required)
python -m scripts.seed_rules

# Demo drugs, patients, and actors for exploring the API (optional)
python -m scripts.seed_demo_data

# Structured test-case fixtures matching spec section 11 (optional)
python -m scripts.seed_test_case_fixtures
```

### 8. Run the server

```bash
uvicorn app.main:app --reload
```

Swagger UI: http://localhost:8000/docs · ReDoc: http://localhost:8000/redoc

Every request/response field carries a `description`; every non-2xx response
an endpoint can produce is declared on that endpoint via `responses=`, not
just documented globally. All error bodies share one shape:

```json
{"error_code": "patient_not_found", "message": "...", "detail": {}}
```

`error_code` is stable and meant to be switched on; `message` is safe to show
directly in a UI. Field-validation failures (missing/out-of-range fields) come
back in the same shape as domain errors (`error_code: "validation_error"`,
with the field-level detail under `detail.errors`) -- one shape to handle
everywhere.

## Tests

```bash
pytest                    # everything (needs both Postgres DBs migrated)
pytest tests/domain        # rule engine only -- no DB needed, runs in ms
pytest tests/api           # full stack, real Postgres (T11, T13, T14, T15 live here)
```

`tests/domain/test_rules_engine.py::test_t7_...` is the spec's ship-blocking
test (section 7): it empties the rule table completely and confirms the
built-in fever failsafe still creates a Critical flag. Do not skip or weaken
this test.

`tests/api/test_t13_reject_system_minutes.py` inserts directly against the
`care_action` table with a system-typed actor, bypassing the API layer
entirely, to prove the `reject_system_minutes` Postgres trigger (migration
`0002`) is the actual guarantee -- not just the 403 check in
`flag_service.log_call`.

## How the rule engine works

A `RuleDefinition` row picks a `rule_type` (a registered strategy function in
`app/domain/rules/strategies.py`) and supplies its own thresholds via `params`
JSON. Tuning R1's pain threshold from 7 to 8, or adding an eleventh rule that
fits an existing shape (another `threshold_gte`, say), is a data change via
`POST /admin/rules` -- no code release. Only a genuinely new rule *shape*
needs a new strategy function.

Editing a rule never mutates a version that may already have fired: it
inserts a new version and closes out the previous one's `effective_to`, so
"which version of a rule was in force on a given date" is always
reconstructable (spec section 5).

Two rules bypass this table entirely and are hardcoded in
`app/domain/rules/failsafes.py` (spec section 7):

- Fever reported by a patient on a biologic or similar drug -> Critical, always.
- A positive answer to a self-harm question -> Critical, always. (The
  depression screen this feeds doesn't exist yet in this version -- the hook
  is wired now via `follow_up_answers["self_harm"]` so a future screen only
  has to set that key.)

They run after the DB-defined rule table, so they still work if that table is
empty, wrong, or misconfigured.

`D3-09` ("three days in a row with no check-in") is the one rule that runs on
a timer instead of reacting to a submission -- see `app/jobs/no_checkin_timer.py`.
It goes through the same `flags.reconcile()` dedup path as every other rule.

## Known limitations / open items

Carried forward from spec section 12 -- these are product/clinical decisions,
not implementation gaps:

- **Thresholds**: every number in the seeded rules is a placeholder
  (`threshold_source: "demo-placeholder"` on `GET /admin/rules`). Needs a
  clinical source and sign-off per rule before it fires for a real patient.
- **The fever message**: the wording a patient would see when the fever rule
  fires needs physician review, not developer-written copy. Not yet modeled
  as a distinct field -- would live as a `message_template` alongside
  `description` on `RuleDefinition`.
- **Sustained illness**: because the usual score is the median of the last 14
  days, a flare lasting more than about a week pulls the usual score up with
  it and `D3-04` (the change rule) goes quiet. Correct for spotting *change*,
  wrong for spotting someone who is simply *staying* sick. Not fixed here;
  the strategy registry is built to make a future `sustained_high` rule type
  a data addition, not an engine change.
- **Notes are excluded from the work list** (`flag_service.get_work_list`)
  but included everywhere else (admin list month strip, monthly summary flags
  table) -- confirmed as the intended scope of "recorded but not work."
- **Time and organisation**: `CareAction.organisation_id` is copied from the
  acting actor at insert time and never reconciled afterward. This needs to be
  a settled decision before any of this data supports a billing claim.
- **The name**: the score is the "D3 score," never RAPID3/DAS28/CDAI --
  enforced by field naming (`today_score`/`usual_score`, never renamed) and
  by `scoring.py`'s docstring. Worth a lint rule if this codebase grows.

## What's deliberately not built (per spec section 1)

EHR integration, real text messaging, real login/auth, real patient data,
joint counts, prior-authorization or copay-assistance workflows, and a
rendered/printable PDF for the monthly summary (the summary endpoint returns
structured JSON; rendering is a frontend concern).
