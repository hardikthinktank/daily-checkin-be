"""Turns a set of rule firings into work-item intents (spec section 8,
"Repeat firings").

If the same rule fires again for the same patient while the previous flag
is still open and less than 72 hours old, do not create a second flag --
add an event to the existing one and bump its count. If the repeat comes
in at a higher level, raise the level of the open flag. Never lower it
quietly.

Pure function: takes firings + a view of currently-open flags, returns a
list of intents. The service layer is the only thing that turns an intent
into an actual database write -- keeping this testable without a DB
(T9's "5 straight days of high pain = one flag with 5 events" case).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from app.domain.rules.types import FlagLevel, RuleFiring

DEDUP_WINDOW = timedelta(hours=72)


@dataclass(frozen=True)
class OpenFlagView:
    """What the service layer knows about one currently-open flag, handed
    into reconcile() so it can decide create-vs-add-event without a query
    inside the pure function.
    """

    flag_id: Any
    rule_code: str
    level: FlagLevel
    last_fired_at: datetime


@dataclass(frozen=True)
class FlagIntent:
    kind: Literal["create", "add_event"]
    firing: RuleFiring
    existing_flag_id: Any | None = None
    raise_to_level: FlagLevel | None = None


def reconcile(
    firings: list[RuleFiring],
    open_flags: list[OpenFlagView],
    now: datetime,
    dedup_window: timedelta = DEDUP_WINDOW,
) -> list[FlagIntent]:
    intents: list[FlagIntent] = []
    for firing in firings:
        match = next(
            (
                f
                for f in open_flags
                if f.rule_code == firing.rule_code and (now - f.last_fired_at) < dedup_window
            ),
            None,
        )
        if match is None:
            intents.append(FlagIntent(kind="create", firing=firing))
            continue
        raise_to = firing.level if firing.level > match.level else None
        intents.append(
            FlagIntent(
                kind="add_event",
                firing=firing,
                existing_flag_id=match.flag_id,
                raise_to_level=raise_to,
            )
        )
    return intents
