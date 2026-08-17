"""Orchestrates one check-in submission end to end (spec section 2):
idempotency -> same-day versioning -> score/usual-score -> rule engine ->
failsafes -> flag reconciliation -> persistence. This is the only layer
that both talks to the database and calls into app.domain.

submit_checkin() handles the initial 3-answer submission. submit_followups()
handles the patient answering the follow-up questions the first call asked
for, re-running the exact same evaluate-and-reconcile step (spec section 2,
step 4) -- which is what lets a fever answer turn an Urgent day into a
Critical one (T5) without any special-casing.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CheckIn, CheckinFollowupLog, Patient
from app.domain.rules.engine import evaluate, pending_followups
from app.domain.rules.failsafes import check_failsafes
from app.domain.rules.flags import reconcile
from app.domain.rules.types import FlagLevel
from app.domain.scoring import score_change, today_score, usual_score
from app.services import context_builder
from app.services.errors import CheckinNotFoundError, PatientNotFoundError
from app.services.flag_apply import apply_intents


@dataclass
class CheckinResult:
    checkin: CheckIn
    required_followups: tuple[str, ...]
    day_level: FlagLevel | None
    created: bool  # False when this was an idempotent replay (T11)


def _day_level(firings) -> FlagLevel | None:
    levels = [f.level for f in firings]
    return max(levels) if levels else None


async def _load_patient(session: AsyncSession, patient_id) -> Patient:
    patient = await session.get(Patient, patient_id)
    if patient is None:
        raise PatientNotFoundError(detail={"patient_id": str(patient_id)})
    return patient


async def _run_engine_and_reconcile(session: AsyncSession, patient: Patient, checkin: CheckIn) -> list:
    """Evaluates every rule against `checkin`'s current state, reconciles
    the result against open flags, and WRITES the resulting Flag/
    FlagEvent rows. Returns the firings (DB rules + failsafes combined)
    so the caller can compute required_followups and day_level.
    """
    ctx = await context_builder.build_context(session, patient, checkin)
    rule_table = await context_builder.load_active_rules(session, as_of=checkin.submitted_at)

    db_firings = evaluate(ctx, rule_table)
    already_fired = frozenset(f.rule_code for f in db_firings)
    failsafe_firings = check_failsafes(ctx, already_fired_rule_codes=already_fired)
    all_firings = [*db_firings, *failsafe_firings]

    open_flags = await context_builder.load_open_flags(session, patient.id)
    now = datetime.now(timezone.utc)
    intents = reconcile(all_firings, open_flags, now)
    await apply_intents(session, patient.id, intents, now=now, checkin_id=checkin.id)

    return all_firings


async def submit_checkin(
    session: AsyncSession,
    patient_id: uuid.UUID,
    *,
    client_submission_id: str,
    fatigue: int,
    pain: int,
    swelling: int,
    checkin_date: date | None = None,
) -> CheckinResult:
    patient = await _load_patient(session, patient_id)
    checkin_date = checkin_date or date.today()

    existing = await session.scalar(
        select(CheckIn).where(CheckIn.client_submission_id == client_submission_id)
    )
    if existing is not None:
        return await _idempotent_replay(session, patient, existing)

    prior_current = await session.scalar(
        select(CheckIn).where(
            CheckIn.patient_id == patient_id,
            CheckIn.checkin_date == checkin_date,
            CheckIn.is_current.is_(True),
        )
    )
    version = 1
    if prior_current is not None:
        # A second full submission the same day replaces the first. The
        # first version is kept, not erased (spec section 3).
        prior_current.is_current = False
        version = prior_current.version + 1

    recent = await context_builder.load_recent_records(session, patient_id, before_date=checkin_date)
    score = today_score(fatigue, pain, swelling)
    usual = usual_score([r.today_score for r in recent])
    change = score_change(score, usual)

    checkin = CheckIn(
        patient_id=patient_id,
        checkin_date=checkin_date,
        client_submission_id=client_submission_id,
        fatigue=fatigue,
        pain=pain,
        swelling=swelling,
        today_score=score,
        usual_score=usual,
        change=change,
        follow_up_answers={},
        version=version,
        is_current=True,
        supersedes_id=prior_current.id if prior_current else None,
    )
    session.add(checkin)

    try:
        await session.flush()
    except IntegrityError:
        # Two concurrent submissions raced on the same client_submission_id
        # (the phone retried before the first response came back). The
        # loser rolls back and replays the winner's result -- still "no
        # second record, no new flags" (T11), just under contention.
        await session.rollback()
        existing = await session.scalar(
            select(CheckIn).where(CheckIn.client_submission_id == client_submission_id)
        )
        return await _idempotent_replay(session, patient, existing)

    firings = await _run_engine_and_reconcile(session, patient, checkin)
    await session.commit()

    return CheckinResult(
        checkin=checkin,
        required_followups=pending_followups(firings, checkin.follow_up_answers),
        day_level=_day_level(firings),
        created=True,
    )


async def _idempotent_replay(session: AsyncSession, patient: Patient, checkin: CheckIn) -> CheckinResult:
    """T11: the same client_submission_id arrived again. Recompute what
    the response should say (read-only -- rules are pure functions of
    already-persisted state) without writing a second record or a new
    flag.
    """
    ctx = await context_builder.build_context(session, patient, checkin)
    rule_table = await context_builder.load_active_rules(session, as_of=checkin.submitted_at)
    db_firings = evaluate(ctx, rule_table)
    already_fired = frozenset(f.rule_code for f in db_firings)
    failsafe_firings = check_failsafes(ctx, already_fired_rule_codes=already_fired)
    firings = [*db_firings, *failsafe_firings]
    return CheckinResult(
        checkin=checkin,
        required_followups=pending_followups(firings, checkin.follow_up_answers),
        day_level=_day_level(firings),
        created=False,
    )


async def submit_followups(
    session: AsyncSession, checkin_id: uuid.UUID, answers: dict[str, str]
) -> CheckinResult:
    """Patient answers the follow-up questions a rule asked for, on the
    same screen (spec section 2, step 4). Amends the check-in in place
    (no version bump -- that's reserved for a full 3-answer resubmission,
    spec section 3) and re-runs the engine so a fever answer can turn an
    Urgent day into a Critical one (T5).
    """
    checkin = await session.get(CheckIn, checkin_id)
    if checkin is None:
        raise CheckinNotFoundError(detail={"checkin_id": str(checkin_id)})

    patient = await _load_patient(session, checkin.patient_id)

    merged = {**checkin.follow_up_answers, **answers}
    checkin.follow_up_answers = merged
    session.add(CheckinFollowupLog(checkin_id=checkin.id, answers=answers))

    firings = await _run_engine_and_reconcile(session, patient, checkin)
    await session.commit()

    return CheckinResult(
        checkin=checkin,
        required_followups=pending_followups(firings, checkin.follow_up_answers),
        day_level=_day_level(firings),
        created=False,
    )
