# Daily Check-In Backend — API Documentation

This is a complete reference for every HTTP endpoint this service exposes, written
for whoever (human or AI) is wiring a frontend up to it. It covers request/response
shapes, every enum, the uniform error format, and the non-obvious business rules a
frontend needs to get right (idempotency, the two-step check-in flow, follow-up
gating, flag deduplication). Pair this with the live interactive docs — they always
reflect the exact running code — at:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- Raw OpenAPI 3.1 JSON: `http://localhost:8000/openapi.json`

Architecture and setup instructions live in `README.md`; this document only covers
the API surface.

## 0. The essentials

| | |
|---|---|
| **Base URL (dev)** | `http://localhost:8000` |
| **Auth** | None. No login, no tokens, no API keys — every endpoint is open. Do not build an auth flow around this API; if/when real auth is added it will be a breaking change layered on top. |
| **CORS** | Wide open (`allow_origins=["*"]`) in dev. Locked down in non-dev environments (see `app/config.py`'s `environment` setting) — a frontend build targeting a non-dev deployment needs its origin allow-listed there. |
| **Content type** | `application/json` for every request body and response. |
| **IDs** | UUIDv4 strings everywhere (`patient_id`, `flag_id`, `actor_id`, `checkin_id`, `rule_id`, `drug_id`). |
| **Dates** | `YYYY-MM-DD` (ISO 8601 date, no time) for calendar dates like `checkin_date`, `enrollment_date`, `month`. |
| **Timestamps** | Full ISO 8601 datetime with timezone, e.g. `"2026-08-15T13:42:20.306752Z"`, for `submitted_at`, `created_at`, `fired_at`, etc. |
| **Numbers as scores** | `today_score`, `usual_score`, `change` are decimals rounded to one place (e.g. `5.7`), returned as JSON numbers. |

## 1. Error handling — one shape, everywhere

Every non-2xx response, **including field-validation failures**, has exactly this
body:

```json
{
  "error_code": "patient_not_found",
  "message": "No patient exists with that ID.",
  "detail": {}
}
```

- `error_code` — stable, machine-readable. **Switch on this**, never on `message` or
  the HTTP status alone (several different problems can share a status code, e.g.
  404 is used for five different "not found" cases).
- `message` — human-readable, safe to render directly in a UI as-is.
- `detail` — optional structured context (offending IDs, field names). For
  validation errors specifically, `detail.errors` is FastAPI's field-level error
  array (`loc`, `msg`, `type` per bad field).

### Status codes used

| Status | Meaning |
|---|---|
| `200` | Success (GET, or a POST that doesn't create a new resource). |
| `201` | Success, a new resource was created (`POST /patients/{id}/checkins`, `POST /patients`, `POST /drugs`, `POST /actors`). |
| `403` | The actor is not allowed to perform this action (system actor trying to log a call). |
| `404` | Referenced resource doesn't exist (bad patient/flag/checkin/drug/actor ID). |
| `409` | Conflicts with current state (duplicate MRN/drug name, double-acknowledge race, acting on an already-resolved flag). |
| `422` | Request was well-formed JSON but failed field validation, OR is semantically invalid per a domain rule (e.g. unknown `rule_type`). |
| `500` | Unhandled server error — logged server-side; body still follows the same `ErrorResponse` shape with `error_code: "internal_error"`. |

### Full `error_code` catalogue

| `error_code` | HTTP status | Raised by |
|---|---|---|
| `patient_not_found` | 404 | Any endpoint taking `patient_id` |
| `checkin_not_found` | 404 | `POST /checkins/{checkin_id}/followups` |
| `flag_not_found` | 404 | Any endpoint taking `flag_id` |
| `actor_not_found` | 404 | Any endpoint taking `actor_id` |
| `drug_not_found` | 404 | `POST /patients` with a bad `current_drug_id` |
| `duplicate_mrn` | 409 | `POST /patients` with an MRN already in use |
| `duplicate_drug_name` | 409 | `POST /drugs` with a name already in use |
| `already_acknowledged` | 409 | `POST /flags/{id}/acknowledge` racing another acknowledger |
| `flag_already_resolved` | 409 | Acting on a flag that's already resolved |
| `system_actor_forbidden` | 403 | `POST /flags/{id}/log-call` with a system-type `actor_id` |
| `invalid_followup_answer` | 422 | A follow-up answer isn't a valid choice for that question |
| `unknown_rule_type` | 422 | `POST /admin/rules` with a `rule_type` the engine doesn't recognize |
| `invalid_rule_params` | 422 | `POST /admin/rules` with `params` missing keys the `rule_type` requires |
| `validation_error` | 422 | Pydantic field validation failed (missing/out-of-range/wrong-type field) |
| `internal_error` | 500 | Unhandled exception |

## 2. Enums

Use these exact string values — they're literal enums on both sides, not
free text.

**`FlagLevel`** (ordered lowest → highest): `"Note"` · `"Review"` · `"Urgent"` · `"Critical"`

**`FlagStatus`**: `"open"` · `"acknowledged"` · `"escalated"` · `"resolved"`

**`ActorType`**: `"human"` · `"system"` (system actors can never log calls / record minutes)

**`ActorRole`**: `"patient"` · `"care_manager"` · `"physician"` · `"admin"` · `"system"`

**`CareActionType`**: `"acknowledge"` · `"log_call"` · `"escalate"` · `"resolve"`

**`CallType`**: `"phone"` · `"video"` · `"async_message"` — only `phone`/`video` count as
a live interaction and turn on a patient's monthly live-call marker; `async_message`
never does, no matter how many messages went back and forth.

### Follow-up question codes and their allowed values

Sent back on a check-in as `required_followups: string[]`; answered via
`POST /checkins/{id}/followups`. Every field also accepts `"skipped"` instead of a
real answer (recorded as explicitly skipped, not as missing) — the client should never
just omit a question the patient declined.

| Code | Asked by | Allowed values |
|---|---|---|
| `days_at_level` | R1 (pain ≥ 7) | `"1"` · `"2-3"` · `"4-7"` · `"more than 7"` |
| `new_joint` | R1 | `"yes"` · `"no"` · `"not sure"` |
| `which_joints` | R2 (swelling ≥ 7) | array of any of: `"hands"` `"wrists"` `"elbows"` `"shoulders"` `"knees"` `"ankles"` `"feet"` |
| `morning_stiffness` | R2 (also feeds R7) | `"under 30 min"` · `"30-60 min"` · `"over 60 min"` |
| `sleep` | R3 (fatigue streak) | `"fine"` · `"broken"` · `"poor most nights"` |
| `medication` | R4 (score change) | `"yes"` · `"no"` |
| `reason` | R8 (medication = no) | `"cost"` · `"side effects"` · `"forgot"` · `"ran out"` · `"other"` |
| `fever` | R1/R2/R5, only for patients on a biologic-or-similar drug | `"yes"` · `"no"` — **a `"yes"` here is always Critical**, regardless of anything else |

No free text on any of these — every answer must be a button/enum value, never an
open string (except `note`/`reason` fields elsewhere, which are plain text).

## 3. Core flows a frontend needs to implement

### 3.1 Patient daily check-in (the phone app)

This is a **two-step** flow, not one call:

```
1. POST /patients/{patient_id}/checkins        (the 3 required daily numbers)
   -> response includes required_followups: string[] and day_level

2. IF required_followups is non-empty:
   POST /checkins/{checkin_id}/followups        (checkin_id from step 1's response)
   -> response includes an UPDATED day_level and possibly still-non-empty
      required_followups (a follow-up answer can itself unlock nothing further
      in this version, but always re-check the field)
```

- **Idempotency is built in.** Generate a fresh random `client_submission_id`
  (e.g. `crypto.randomUUID()`) per submission attempt and retry with the *same*
  ID if the request times out or the network drops mid-flight. The server
  guarantees exactly one record and one set of flags even if the same ID arrives
  twice — the second response has `"created": false` and is otherwise identical.
  **Never generate a new ID on retry.**
- A **second, distinct** submission for the same patient on the same calendar day
  (different `client_submission_id`) is treated as a correction: it supersedes the
  first (which is kept in history, not deleted) and bumps `version`.
- `day_level` in the response is the highest flag level triggered **so far today**
  across every rule that has fired (including from the follow-up step) — `null`
  means nothing fired. Useful for an immediate "thanks, we've got it" vs. "we're
  going to review this" UI branch.
- The `fever` follow-up only ever appears in `required_followups` for patients on
  a biologic-or-similar drug (check `PatientResponse.current_drug.is_biologic_or_similar`
  if you need to pre-branch UI, but you don't need to — the backend already omits
  it for other patients).

**Example — submit today's answers:**

```http
POST /patients/2ad8f99a-5a6d-4fa6-a213-25e0940ef6cd/checkins
Content-Type: application/json

{
  "client_submission_id": "b3f1c2e8-6b7d-4e9a-9c1a-2f6b8e0d4c11",
  "fatigue": 7,
  "pain": 8,
  "swelling": 8
}
```

```json
{
  "id": "9c6a1f2e-...",
  "patient_id": "2ad8f99a-5a6d-4fa6-a213-25e0940ef6cd",
  "checkin_date": "2026-08-15",
  "fatigue": 7,
  "pain": 8,
  "swelling": 8,
  "today_score": 7.7,
  "usual_score": 3.0,
  "change": 4.7,
  "follow_up_answers": {},
  "version": 1,
  "is_current": true,
  "submitted_at": "2026-08-15T09:12:03.441Z",
  "required_followups": ["days_at_level", "new_joint", "which_joints", "morning_stiffness", "fever", "medication"],
  "day_level": "Urgent",
  "created": true
}
```

**Example — answer the follow-ups:**

```http
POST /checkins/9c6a1f2e-.../followups
Content-Type: application/json

{
  "days_at_level": "2-3",
  "new_joint": "yes",
  "which_joints": ["knees", "ankles"],
  "morning_stiffness": "over 60 min",
  "fever": "yes",
  "medication": "yes"
}
```

Send only the fields the patient actually answered/skipped — omitted fields are
left untouched (this endpoint merges into `follow_up_answers`, it doesn't replace
it), so it's safe to call it more than once as different questions get answered.
Because `fever: "yes"` was included and this patient is on a biologic, `day_level`
in the response jumps to `"Critical"`.

### 3.2 Care manager console

```
GET  /care-manager/worklist                      -- triage queue
GET  /flags/{flag_id}                             -- "why did this fire", full history
POST /flags/{flag_id}/acknowledge                 -- claim it
POST /flags/{flag_id}/log-call                    -- record time spent (human actors only)
POST /flags/{flag_id}/escalate                    -- send to physician
POST /flags/{flag_id}/resolve                     -- close it out
```

- The worklist **never contains `Note`-level flags** — those are recorded but are
  explicitly not "work" per the spec. Don't filter client-side; the server already
  excludes them.
- Sort order is server-side: `Critical` first, then by recency. Render in the order
  received.
- `POST /flags/{id}/acknowledge` is a race-safe claim: if two care managers click
  at the same instant, the loser gets `409 already_acknowledged` — show that as
  "someone else just took this," not a generic error, and refresh the flag.
- `POST /flags/{id}/log-call` needs a **human** `actor_id`. Passing a system
  actor gets `403 system_actor_forbidden`. Filter your actor picker to
  `actor_type === "human"` to avoid ever hitting this in normal use.
- `call_type: "phone"` or `"video"` on a log-call is what turns on that patient's
  monthly live-call marker; `"async_message"` never does. If your UI has a
  "logged a message thread" action distinct from "logged a call," map it to
  `async_message`.
- Nothing is ever hard-deleted. `resolve` just moves `status` to `"resolved"`;
  the full `events`/`actions` history stays on `GET /flags/{id}`.

### 3.3 Admin list (operations dashboard)

```
GET /admin/patients?month=2026-08-01
```

One row per patient, already aggregated server-side — no need to fetch
individual patients and stitch data together. `month` accepts *any* date within
the target month (defaults to the current month if omitted); the response
always represents the whole calendar month.

`sixteen_day_marker_met` / `sixteen_day_marker_short_by` and
`live_call_this_month` are **operational facts, not billing signals** — display
them as "16-day data marker" / "live call this month," never as anything implying
billing eligibility. Note that `open_items` here counts flags at **any** level
including Note (unlike the care-manager worklist, which excludes Note) — the two
numbers on different screens are intentionally different.

### 3.4 Monthly summary (physician view)

```
GET  /patients/{patient_id}/monthly-summary?month=2026-08-01
POST /patients/{patient_id}/monthly-summary/rebuild?month=2026-08-01
```

Returns everything needed to render one printable page: header, a symptom-line
chart series, a score chart (with `usual_score_line` / `usual_plus_3_line` as
static reference lines, not per-point data), a month strip (one cell per day,
colored by that day's level, `null` = no check-in), a flags table, a
chronological team-actions log, and `record_facts` (the same 16-day/live-call
markers as the admin list, scoped to just this patient/month).

This is served from a cache that's rebuilt automatically on every relevant write
(new check-in, new flag, new care action) — `GET` should normally be near-instant.
The `POST .../rebuild` variant forces a synchronous rebuild; use it for a
"refresh" button or right after seeding test data, not on every page load.

### 3.5 Rule administration (admin/config screen, if you're building one)

```
GET  /admin/rules?active_only=true      -- the effective rule set
GET  /admin/rules/{rule_id}             -- one specific version
POST /admin/rules                       -- publish a new version
```

Rules are versioned, append-only rows. `POST` always creates a **new** version —
if `rule_code` already has an active version, that one is closed out
(`effective_to` set to now) and the new one takes over; if it's a brand-new
`rule_code`, this becomes version 1. A rule that has already fired for anyone is
never mutated in place, so "what version was in force on a given date" is always
reconstructable from the flags it created.

`params` is strategy-specific and validated server-side against the exact keys
`rule_type` reads — get it wrong and you get `422 invalid_rule_params` instead of
a rule that silently 500s the first time it tries to fire. See §5 below for the
full `rule_type` → required `params` table.

## 4. Full endpoint reference

### Patient check-ins

#### `POST /patients/{patient_id}/checkins`
Submit today's three answers. Returns `201`.

Request body (`CheckinSubmitRequest`):
```json
{
  "client_submission_id": "string, 1-128 chars, required — see idempotency note in §3.1",
  "fatigue": "integer 1-10, required",
  "pain": "integer 1-10, required",
  "swelling": "integer 1-10, required",
  "checkin_date": "YYYY-MM-DD, optional — defaults to server's today; only override for backfill/testing"
}
```
Response (`CheckinResponse`) — see full example in §3.1. Errors: `404 patient_not_found`, `422 validation_error`.

#### `POST /checkins/{checkin_id}/followups`
Answer whichever follow-up questions the last evaluation asked for. Returns `200`.

Request body (`FollowupAnswersRequest`) — every field optional, send only what's
answered/skipped:
```json
{
  "days_at_level": "1 | 2-3 | 4-7 | more than 7 | skipped",
  "new_joint": "yes | no | not sure | skipped",
  "which_joints": ["hands", "wrists", "elbows", "shoulders", "knees", "ankles", "feet"],
  "morning_stiffness": "under 30 min | 30-60 min | over 60 min | skipped",
  "sleep": "fine | broken | poor most nights | skipped",
  "medication": "yes | no | skipped",
  "reason": "cost | side effects | forgot | ran out | other | skipped",
  "fever": "yes | no | skipped"
}
```
`which_joints` can also just be `"skipped"` instead of an array. Response is the
same `CheckinResponse` shape. Errors: `404 checkin_not_found`, `422 validation_error`.

### Care manager console

#### `GET /care-manager/worklist`
No params. Returns `FlagResponse[]`, Critical-first, Note-level excluded.

```json
[
  {
    "id": "660d8caa-7ff8-47c4-bffb-61c04c175a73",
    "patient_id": "297d5412-0dde-4232-a09f-7f5987148a41",
    "rule_code": "D3-01",
    "rule_version": "1",
    "level": "Review",
    "status": "open",
    "first_fired_at": "2026-08-15T12:37:32.118107Z",
    "last_fired_at": "2026-08-15T13:44:27.492854Z",
    "event_count": 4,
    "why_snapshot": { "field": "pain", "value": 8, "gte": 7 },
    "acknowledged_by": null,
    "acknowledged_at": null,
    "created_at": "2026-08-15T12:37:32.092877Z",
    "updated_at": "2026-08-15T13:44:27.434573Z"
  }
]
```
`rule_version` is `"builtin-1"` instead of a number when `rule_code` starts with
`FAILSAFE-` (the two hardcoded protections from spec §7 — fever-on-a-biologic and
self-harm — rather than a normal DB-defined rule).

#### `GET /flags/{flag_id}`
Everything on the worklist row, plus `rule_description` (the human sentence, e.g.
"Pain is 7 or higher."), `care_manager_action` (what to do about it), and the full
`events`/`actions` history:

```json
{
  "...(all FlagResponse fields)...": "...",
  "rule_description": "Pain is 7 or higher.",
  "care_manager_action": "Review within one business day.",
  "events": [
    { "id": "...", "checkin_id": "...", "rule_version": "1", "fired_at": "2026-08-15T12:37:32Z", "numbers_snapshot": {"field": "pain", "value": 8, "gte": 7} }
  ],
  "actions": [
    { "id": "...", "flag_id": "...", "actor_id": "...", "action_type": "acknowledge", "minutes": null, "call_type": null, "reason": null, "note": null, "created_at": "..." }
  ]
}
```
`events[].checkin_id` is `null` for timer-fired rules (currently only R9, the
three-days-of-silence rule — nothing to link to since no check-in triggered it).
Errors: `404 flag_not_found`.

#### `POST /flags/{flag_id}/acknowledge`
```json
{ "actor_id": "must be a human or physician actor's UUID" }
```
Returns the updated `FlagResponse`. Errors: `404 flag_not_found` / `actor_not_found`,
`409 already_acknowledged`, `409 flag_already_resolved`.

#### `POST /flags/{flag_id}/log-call`
```json
{
  "actor_id": "must be a HUMAN actor's UUID — system actors get 403",
  "minutes": "integer >= 0, required",
  "call_type": "phone | video | async_message",
  "note": "string, optional, max 2000 chars"
}
```
Returns `CareActionResponse`. Errors: `404`, `403 system_actor_forbidden`,
`422 validation_error`.

#### `POST /flags/{flag_id}/escalate`
```json
{ "actor_id": "uuid", "reason": "string, 1-500 chars, required" }
```
Returns `CareActionResponse`, sets flag status to `"escalated"`. Errors: `404`.

#### `POST /flags/{flag_id}/resolve`
```json
{ "actor_id": "uuid", "note": "string, 1-2000 chars, required" }
```
Returns `CareActionResponse`, sets flag status to `"resolved"`. Errors: `404`,
`422` (empty note).

### Admin list

#### `GET /admin/patients?month=YYYY-MM-DD`
`month` optional (any date in the target month; defaults to current month).
Returns `AdminListRowResponse[]`, one row per patient:

```json
{
  "patient_id": "d7ec9f7e-8a55-4bdc-9041-fdf65c51f47c",
  "patient_name": "Jordan Ellis",
  "mrn": "MRN-1001",
  "diagnosis": "Rheumatoid arthritis",
  "therapy": "Adalimumab (biologic)",
  "month_strip": [{ "day": 1, "level": null }, { "day": 2, "level": "Review" }, "... one per day of the month"],
  "checkins_done": 15,
  "checkins_expected": 31,
  "checkins_pct": 48.4,
  "average_score": 3.0,
  "last_checkin_date": "2026-08-15",
  "last_checkin_level": "Note",
  "open_items": 1,
  "minutes_this_month": 0,
  "live_call_this_month": false,
  "days_of_data_this_month": 15,
  "sixteen_day_marker_met": false,
  "sixteen_day_marker_short_by": 1
}
```

### Monthly summary

#### `GET /patients/{patient_id}/monthly-summary?month=YYYY-MM-DD`
#### `POST /patients/{patient_id}/monthly-summary/rebuild?month=YYYY-MM-DD`
Both return `MonthlySummaryResponse`:

```json
{
  "header": {
    "patient_id": "...", "patient_name": "...", "month": "2026-08-01",
    "drug": "Adalimumab (biologic)", "days_reported": 15, "days_in_month": 31
  },
  "symptom_chart": [{ "date": "2026-08-01", "fatigue": 3, "pain": 3, "swelling": 3 }],
  "score_chart": {
    "series": [{ "date": "2026-08-01", "today_score": 3.0, "usual_score": 3.0 }],
    "usual_score_line": 3.0,
    "usual_plus_3_line": 6.0
  },
  "days_by_level": { "none": 8, "Note": 7, "Review": 0, "Urgent": 0, "Critical": 0 },
  "month_strip": [{ "day": 1, "level": null }],
  "flags_table": [
    { "rule_code": "D3-01", "rule_version": "1", "what_fired_it": "Pain is 7 or higher.",
      "level": "Review", "first_fired_at": "2026-08-15T12:37:32Z", "event_count": 4,
      "status": "open", "minutes": 10 }
  ],
  "team_actions": [
    { "date": "2026-08-15T13:50:00Z", "action_type": "log_call", "minutes": 10,
      "call_type": "async_message", "reason": null, "note": "Messaged patient." }
  ],
  "record_facts": {
    "days_of_data": 15, "sixteen_day_marker_met": false, "sixteen_day_marker_short_by": 1,
    "live_call_happened": false, "minutes_recorded": 10
  }
}
```
Errors: `404 patient_not_found`.

### Rule administration

#### `GET /admin/rules?active_only=true`
Returns `RuleDefinitionResponse[]`. `active_only=false` includes every historical
version, not just the currently-effective one.

```json
{
  "id": "...", "rule_code": "D3-01", "version": 1, "level": "Review",
  "description": "Pain is 7 or higher.", "rule_type": "threshold_gte",
  "params": { "field": "pain", "gte": 7 },
  "follow_up_questions": ["days_at_level", "new_joint", "fever"],
  "requires_fever_gate": true,
  "care_manager_action": "Review within one business day.",
  "threshold_source": "demo-placeholder",
  "effective_from": "2026-01-01T00:00:00Z", "effective_to": null, "is_active": true
}
```

#### `GET /admin/rules/{rule_id}`
Single rule version by row ID. Errors: `404`.

#### `POST /admin/rules`
```json
{
  "rule_code": "D3-01",
  "level": "Review",
  "description": "Pain is 7 or higher.",
  "rule_type": "threshold_gte",
  "params": { "field": "pain", "gte": 7 },
  "follow_up_questions": ["days_at_level", "new_joint", "fever"],
  "requires_fever_gate": true,
  "care_manager_action": "Review within one business day.",
  "threshold_source": "demo-placeholder"
}
```
Returns the new `RuleDefinitionResponse`. Errors: `422 unknown_rule_type`,
`422 invalid_rule_params`, `422 validation_error`.

### Reference data (patients / drugs / actors)

#### `GET /patients` — list all
#### `POST /patients` — enroll
```json
{
  "name": "string, 1-200 chars",
  "mrn": "string, 1-64 chars, must be unique",
  "diagnosis": "string, 1-200 chars",
  "current_drug_id": "uuid, must reference an existing drug",
  "enrollment_date": "YYYY-MM-DD, optional, defaults to today"
}
```
Returns `201` + `PatientResponse` (includes the nested `current_drug` object).
Errors: `404 drug_not_found`, `409 duplicate_mrn`.

#### `GET /patients/{patient_id}` — errors: `404 patient_not_found`

#### `GET /drugs` — list all
#### `POST /drugs`
```json
{ "name": "string, 1-120 chars, unique", "is_biologic_or_similar": true }
```
Returns `201` + `DrugResponse`. Errors: `409 duplicate_drug_name`.
`is_biologic_or_similar` gates whether the `fever` follow-up is ever asked for
this drug's patients.

#### `GET /actors` — list all
#### `POST /actors`
```json
{ "display_name": "string, 1-200 chars", "actor_type": "human | system", "role": "patient | care_manager | physician | admin | system" }
```
Returns `201` + `ActorResponse`. Use `actor_type: "human"` for every real staff
member — `"system"` actors are for automated/service accounts only and are
rejected everywhere a call/minutes get logged.

### Health

#### `GET /health`
No auth, no params. `{"status": "ok"}`. Use for readiness checks.

## 5. `rule_type` reference (for `POST /admin/rules`)

Only needed if you're building a rule-editing screen. Every `rule_type` below is
already used by one of the ten seeded rules (`GET /admin/rules` for real examples) —
`params` must contain **exactly** the keys listed, or the request is rejected with
`422 invalid_rule_params` before it can ever go active.

| `rule_type` | Required `params` keys | Behavior |
|---|---|---|
| `threshold_gte` | `field`, `gte` | Fires when today's `field` (`fatigue`\|`pain`\|`swelling`) ≥ `gte`. |
| `any_field_gte` | `fields`, `gte` | Fires when ANY of `fields` (array) ≥ `gte` today. |
| `streak_gte` | `field`, `gte`, `days` | Fires when `field` ≥ `gte` for `days` consecutive calendar days ending today. |
| `streak_lte_nothing_open` | `field`, `lte`, `days` | Fires when `field` ≤ `lte` for `days` consecutive days ending today AND the patient has nothing open at Review/Urgent/Critical (Note-level flags don't block this). |
| `change_gte` | `gte` | Fires when `today_score - usual_score` ≥ `gte`. Never fires while `usual_score` is null (fewer than 5 prior check-ins). |
| `answer_equals` | `field`, `equals` | Fires when a follow-up answer field equals a fixed value. |
| `fever_and_biologic` | (none) | Fires when `fever` follow-up = `"yes"` AND the patient is on a biologic. Mirrors the hardcoded failsafe (§7 of the spec) — the failsafe still fires independently if this row is ever deleted or broken. |
| `followup_choice_at_least_and_today_gte` | `answer_field`, `at_least`, `today_field`, `today_gte` | Fires when a fixed-choice follow-up answer is at or beyond `at_least` in its ordered list AND `today_field` ≥ `today_gte` today. |
| `no_checkin_streak` | `days` | Evaluated by a scheduled job, not the submission-triggered engine — fires when `days` calendar days have passed with no check-in. |

Valid `follow_up_questions` codes: `days_at_level`, `fever`, `medication`,
`morning_stiffness`, `new_joint`, `reason`, `sleep`, `which_joints` (see §2 for
their allowed answer values).

## 6. Things that will bite you if skipped

- **Always generate `client_submission_id` client-side and persist it with the
  in-flight request** (e.g. in local storage before the network call), so a retry
  after a crash/timeout can reuse it. This is the entire offline/flaky-network
  story for the patient app.
- **Never treat HTTP status alone as the error type.** Two different problems can
  both be a 404 (`patient_not_found` vs `flag_not_found`); switch on `error_code`.
- **`required_followups` can be non-empty after the follow-ups call too** — always
  re-check it in the response rather than assuming one round-trip finishes the
  flow.
- **`day_level` can escalate on the follow-ups call** (a `fever: "yes"` answer
  turning Urgent into Critical) — don't cache the level from step 1 and ignore
  step 2's response.
- **The worklist excludes Note-level flags; the admin list's `open_items` does
  not.** These are two intentionally different counts — don't try to reconcile
  them into one "open flags" number shared across screens.
- **`sixteen_day_marker_met` / `live_call_this_month` are operational facts, not
  billing determinations** — per the spec, presenting them as billing eligibility
  is explicitly out of scope and incorrect.
- **Nothing in this API is clinically validated.** Every threshold has
  `threshold_source: "demo-placeholder"`. Don't let a frontend imply otherwise
  (e.g. don't call the D3 score "RAPID3" or similar in any UI copy).
