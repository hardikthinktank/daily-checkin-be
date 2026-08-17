"""The two rules that can never be switched off (spec section 7).

These are written into the program itself, deliberately NOT stored in the
`rule_definition` table, and run after the DB-defined rule table on every
submission -- so they still work if that table is empty, wrong, or
misconfigured. This is exactly what test T7 checks: empty the rule table
completely and confirm a Critical flag is still created for a feverish
patient on a biologic.

Do not add a way to disable these from the database. If a future rule
change needs to soften this behaviour, that is a product decision that
belongs in a new version of this file, reviewed like any other code
change -- not a row that can be quietly edited or deleted.
"""
from __future__ import annotations

from app.domain.rules.types import CheckinContext, FlagLevel, RuleFiring

# Not a DB row, so not a real version number -- a stable label so these
# firings are still traceable in an audit trail years from now.
FAILSAFE_VERSION = "builtin-1"

FEVER_RULE_CODE = "FAILSAFE-FEVER"
SELF_HARM_RULE_CODE = "FAILSAFE-SELF-HARM"

# The DB-row rule that duplicates the fever failsafe under normal
# operation (spec's R6). When both fire in the same pass, we suppress the
# failsafe firing in favour of the configurable one so a care manager
# doesn't see two flags for the same event. The failsafe still fires on
# its own the moment R6 is missing, wrong, or the whole table is empty.
_FEVER_DB_EQUIVALENT = "D3-06"


def check_failsafes(
    ctx: CheckinContext,
    already_fired_rule_codes: frozenset[str] = frozenset(),
) -> list[RuleFiring]:
    firings: list[RuleFiring] = []

    fever_answer = ctx.today.follow_up_answers.get("fever")
    if (
        fever_answer == "yes"
        and ctx.history.on_biologic
        and _FEVER_DB_EQUIVALENT not in already_fired_rule_codes
    ):
        firings.append(
            RuleFiring(
                rule_code=FEVER_RULE_CODE,
                rule_version=FAILSAFE_VERSION,
                level=FlagLevel.CRITICAL,
                why={"fever": "yes", "on_biologic": True, "source": "builtin_failsafe"},
                ask=(),
            )
        )

    # No self-harm question exists yet (the depression screen this feeds
    # is not built in this version -- spec section 7). The hook is wired
    # now so that when that screen ships, it only has to set
    # follow_up_answers["self_harm"] = "yes"/"no" and this protection
    # applies immediately, with no risk of the new feature forgetting to
    # wire it in.
    if ctx.today.follow_up_answers.get("self_harm") == "yes":
        firings.append(
            RuleFiring(
                rule_code=SELF_HARM_RULE_CODE,
                rule_version=FAILSAFE_VERSION,
                level=FlagLevel.CRITICAL,
                why={"self_harm": "yes", "source": "builtin_failsafe"},
                ask=(),
            )
        )

    return firings
