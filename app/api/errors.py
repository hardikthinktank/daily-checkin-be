"""Maps every service-layer DomainError to an HTTP status code and a
single, uniform error body shape (ErrorResponse). Registered once in
app/main.py via install_exception_handlers().

Every router endpoint also declares its possible non-2xx responses via
the `responses=` kwarg (see app/api/common_responses.py) so the specific
error shapes show up in /docs per endpoint, not just as a global note --
that's what makes them "clearly visible" to whoever is building the
frontend against this API.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.services.errors import (
    ConcurrentAcknowledgeError,
    DomainError,
    DuplicateError,
    FlagAlreadyResolvedError,
    NotFoundError,
    SystemActorForbiddenError,
)

logger = logging.getLogger(__name__)


class ErrorResponse(BaseModel):
    """The shape of every non-2xx JSON body this API returns, including
    validation errors -- one shape for the frontend to branch on,
    everywhere.
    """

    error_code: str = Field(
        ...,
        description="Stable, machine-readable identifier. Safe to switch on in frontend code.",
        examples=["patient_not_found"],
    )
    message: str = Field(
        ...,
        description="Human-readable explanation. Safe to show directly in a UI.",
        examples=["No patient exists with that ID."],
    )
    detail: dict = Field(
        default_factory=dict,
        description="Optional structured context -- offending field names, conflicting IDs, etc.",
    )


_STATUS_BY_ERROR_TYPE: list[tuple[type[DomainError], int]] = [
    (NotFoundError, status.HTTP_404_NOT_FOUND),
    (ConcurrentAcknowledgeError, status.HTTP_409_CONFLICT),
    (FlagAlreadyResolvedError, status.HTTP_409_CONFLICT),
    (DuplicateError, status.HTTP_409_CONFLICT),
    (SystemActorForbiddenError, status.HTTP_403_FORBIDDEN),
    # Fallback for any other DomainError subclass (e.g. InvalidFollowupAnswerError,
    # UnknownRuleTypeError) -- unprocessable, since these are all "your
    # request was well-formed but semantically not allowed" cases.
    (DomainError, status.HTTP_422_UNPROCESSABLE_CONTENT),
]


def _status_for(exc: DomainError) -> int:
    for exc_type, status_code in _STATUS_BY_ERROR_TYPE:
        if isinstance(exc, exc_type):
            return status_code
    return status.HTTP_400_BAD_REQUEST


async def _domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    status_code = _status_for(exc)
    body = ErrorResponse(error_code=exc.error_code, message=exc.message, detail=exc.detail)
    return JSONResponse(status_code=status_code, content=body.model_dump())


async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Reshapes FastAPI's default {"detail": [...]} validation error into
    the same ErrorResponse envelope as every other error, so a frontend
    never has to special-case 422s from bad input vs 422s from a domain
    rule.

    exc.errors() is NOT safe to json.dumps() directly: a `@field_validator`
    that raises ValueError (see RuleVersionCreateRequest's follow-up-code
    check) ends up with that raw exception object embedded in each error's
    ctx.error. jsonable_encoder is what FastAPI's own default handler uses
    to sanitize this -- skipping it is what silently turned a clean 422
    into an unhandled 500 the first time this path was actually exercised.
    """
    body = ErrorResponse(
        error_code="validation_error",
        message="One or more fields failed validation. See detail.errors for specifics.",
        detail={"errors": jsonable_encoder(exc.errors())},
    )
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=body.model_dump())


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    body = ErrorResponse(
        error_code="internal_error",
        message="Something went wrong on the server. This has been logged.",
        detail={},
    )
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=body.model_dump())


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _domain_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
