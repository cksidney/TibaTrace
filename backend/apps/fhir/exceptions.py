from .constants import ISSUE_CODE_EXCEPTION, SEVERITY_ERROR


class FHIRException(Exception):
    """Base exception for FHIR API errors."""
    def __init__(self, message, severity=SEVERITY_ERROR, code=ISSUE_CODE_EXCEPTION, diagnostics=None, expression=None):
        super().__init__(message)
        self.message = message
        self.severity = severity
        self.code = code
        self.diagnostics = diagnostics
        self.expression = expression


class FHIRValidationError(FHIRException):
    """Raised when incoming FHIR payload fails validation."""
    pass


class FHIRNotSupportedError(FHIRException):
    """Raised when an operation, resource, or parameter is not supported."""
    pass


class FHIRReferenceResolutionError(FHIRException):
    """Raised when a reference in a FHIR resource cannot be resolved."""
    pass


class FHIRSecurityError(FHIRException):
    """Raised on authentication or authorization failure."""
    pass


class FHIRIdempotencyError(FHIRException):
    """Raised when an idempotency conflict occurs."""
    pass


class FHIRBusinessRuleError(FHIRException):
    """Raised when domain business rules reject a FHIR command."""
    pass
