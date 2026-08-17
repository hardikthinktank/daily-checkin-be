"""Wires the two background jobs into an in-process APScheduler. Started
from the FastAPI lifespan in app/main.py; there is no separate worker
process for this demo's scale (spec section 1 explicitly scopes this
down to a small working version).
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.jobs.no_checkin_timer import run_no_checkin_timer_standalone
from app.jobs.summary_prebuild import rebuild_all_patients_standalone

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    scheduler = AsyncIOScheduler()
    # R9 -- "three days in a row with no check-in" needs to be checked
    # once a day regardless of whether anyone submits anything.
    scheduler.add_job(
        run_no_checkin_timer_standalone,
        CronTrigger(hour=6, minute=0),
        id="no_checkin_timer",
        replace_existing=True,
    )
    # Monthly summary pre-build -- keeps the physician's read path a
    # cache hit (spec section 10's <5s target).
    scheduler.add_job(
        rebuild_all_patients_standalone,
        CronTrigger(hour=2, minute=0),
        id="summary_prebuild",
        replace_existing=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("scheduler started: no_checkin_timer@06:00, summary_prebuild@02:00")
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
