"""Reusable `responses=` fragments for router decorators, so every
endpoint's possible error shapes show up per-endpoint in /docs (not just
as a global note). Merge the ones that apply:

    @router.post(..., responses={**NOT_FOUND, **CONFLICT})
"""
from __future__ import annotations

from app.api.errors import ErrorResponse


def _err(description: str) -> dict:
    return {"model": ErrorResponse, "description": description}


NOT_FOUND = {404: _err("The referenced resource (patient, check-in, flag, drug, or actor) does not exist.")}
CONFLICT = {409: _err("The request conflicts with current state -- e.g. this flag was already acknowledged by someone else.")}
DUPLICATE = {409: _err("A record with this unique value already exists (e.g. MRN or drug name already in use).")}
FORBIDDEN = {403: _err("The actor is not allowed to perform this action -- e.g. a system actor tried to log a call.")}
UNPROCESSABLE = {422: _err("The request body failed field validation, or violates a domain rule (e.g. an unknown rule_type).")}
