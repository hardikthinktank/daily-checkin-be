"""Domain-level exceptions raised by the service layer. The API layer
(app/api/errors.py) maps each of these to an HTTP status code and a
structured ErrorResponse body, and registers that mapping with FastAPI so
every possible error shows up in the OpenAPI docs per endpoint -- not
just the happy path.
"""
from __future__ import annotations


class DomainError(Exception):
    """Base class. `error_code` is the stable, machine-readable string a
    frontend can switch on; `message` is safe to show a user as-is.
    """

    error_code: str = "domain_error"
    default_message: str = "A domain error occurred."

    def __init__(self, message: str | None = None, *, detail: dict | None = None):
        self.message = message or self.default_message
        self.detail = detail or {}
        super().__init__(self.message)


class NotFoundError(DomainError):
    error_code = "not_found"
    default_message = "The requested resource does not exist."


class PatientNotFoundError(NotFoundError):
    error_code = "patient_not_found"
    default_message = "No patient exists with that ID."


class CheckinNotFoundError(NotFoundError):
    error_code = "checkin_not_found"
    default_message = "No check-in exists with that ID."


class FlagNotFoundError(NotFoundError):
    error_code = "flag_not_found"
    default_message = "No flag exists with that ID."


class ActorNotFoundError(NotFoundError):
    error_code = "actor_not_found"
    default_message = "No actor exists with that ID."


class DrugNotFoundError(NotFoundError):
    error_code = "drug_not_found"
    default_message = "No drug exists with that ID."


class DuplicateError(DomainError):
    """A unique constraint would be violated (e.g. an MRN or drug name
    that's already in use). Raised instead of letting a raw IntegrityError
    surface as a 500.
    """

    error_code = "duplicate"
    default_message = "A record with this unique value already exists."


class DuplicateMrnError(DuplicateError):
    error_code = "duplicate_mrn"
    default_message = "A patient with this MRN already exists."


class DuplicateDrugNameError(DuplicateError):
    error_code = "duplicate_drug_name"
    default_message = "A drug with this name already exists."


class ConcurrentAcknowledgeError(DomainError):
    """Two care managers tried to acknowledge the same flag at once.
    Spec section 8: "the second gets an error rather than silently
    overwriting the first."
    """

    error_code = "already_acknowledged"
    default_message = "This flag was already acknowledged by someone else."


class FlagAlreadyResolvedError(DomainError):
    error_code = "flag_already_resolved"
    default_message = "This flag is already resolved and cannot be acted on further."


class SystemActorForbiddenError(DomainError):
    """App-layer enforcement of spec section 8 / T13: only a human can
    log a call (and therefore record minutes). This exists alongside the
    `reject_system_minutes` database trigger, not instead of it -- the
    trigger is what T13 actually tests.
    """

    error_code = "system_actor_forbidden"
    default_message = "System actors may not log calls or record minutes."


class InvalidFollowupAnswerError(DomainError):
    error_code = "invalid_followup_answer"
    default_message = "One or more follow-up answers are not valid for the question asked."
