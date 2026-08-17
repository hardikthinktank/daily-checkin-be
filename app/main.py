"""FastAPI entry point.

    uvicorn app.main:app --reload

/docs (Swagger UI) and /redoc are both enabled -- every request/response
field carries a description (see app/schemas/), and every non-2xx
response an endpoint can produce is declared via `responses=` so it shows
up there too, not just the happy path. See app/api/errors.py for the
single error-body shape used everywhere.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import install_exception_handlers
from app.api.routers import admin, care_manager, checkins, reference_data, rules_admin, summary
from app.config import settings
from app.jobs.scheduler import shutdown_scheduler, start_scheduler

DESCRIPTION = """
Backend for the daily check-in care-management loop: a patient answers three
questions a day, a rule engine decides what happens next, a care manager
works the results, and the physician gets a monthly picture.

**Every threshold in the seeded rules is a demo placeholder** (see the
`threshold_source` field on `/admin/rules`) -- none of it is clinically
validated. See the project README, section 12, before any of this touches
a real patient.

### Error shape

Every non-2xx response (including field-validation failures) has this shape:

```json
{"error_code": "patient_not_found", "message": "...", "detail": {}}
```

`error_code` is stable and safe to switch on; `message` is safe to show a
user as-is.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(
    title="Daily Check-In Backend",
    description=DESCRIPTION,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.environment == "dev" else [],
    allow_methods=["*"],
    allow_headers=["*"],
)

install_exception_handlers(app)

app.include_router(checkins.router)
app.include_router(care_manager.router)
app.include_router(admin.router)
app.include_router(summary.router)
app.include_router(rules_admin.router)
app.include_router(reference_data.router)


@app.get("/health", tags=["Health"], summary="Liveness check")
async def health() -> dict:
    return {"status": "ok"}
