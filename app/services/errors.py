class AppError(Exception):
    """Base application error."""


class DomainValidationError(AppError):
    """Invalid user input or archive contents."""


class NotFoundError(AppError):
    """Requested resource does not exist."""


class ConflictError(AppError):
    """Illegal state transition or conflicting update."""
