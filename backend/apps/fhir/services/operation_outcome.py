from typing import List, Optional

from fhir.resources.operationoutcome import OperationOutcome, OperationOutcomeIssue

from apps.fhir.constants import (
    ISSUE_CODE_EXCEPTION,
    ISSUE_CODE_INVALID,
    ISSUE_CODE_STRUCTURE,
    SEVERITY_ERROR,
    SEVERITY_FATAL,
)
from apps.fhir.exceptions import FHIRException


class OperationOutcomeFactory:
    """Factory for creating FHIR OperationOutcome resources."""

    @classmethod
    def create(
        cls,
        severity: str,
        code: str,
        diagnostics: Optional[str] = None,
        details_text: Optional[str] = None,
        expression: Optional[List[str]] = None
    ) -> OperationOutcome:
        issue = OperationOutcomeIssue(
            severity=severity,
            code=code,
            diagnostics=diagnostics,
        )
        if details_text:
            issue.details = {"text": details_text}
        if expression:
            issue.expression = expression

        return OperationOutcome(issue=[issue])

    @classmethod
    def create_error(cls, message: str, code: str = ISSUE_CODE_EXCEPTION) -> OperationOutcome:
        return cls.create(
            severity=SEVERITY_ERROR,
            code=code,
            diagnostics=message,
        )

    @classmethod
    def create_warning(cls, message: str, code: str = ISSUE_CODE_INVALID) -> OperationOutcome:
        return cls.create(
            severity="warning",
            code=code,
            diagnostics=message,
        )

    @classmethod
    def from_exception(cls, exc: Exception) -> OperationOutcome:
        """Create an OperationOutcome from a Python exception."""
        if isinstance(exc, FHIRException):
            return cls.create(
                severity=exc.severity,
                code=exc.code,
                diagnostics=exc.diagnostics or str(exc.message),
                expression=[exc.expression] if exc.expression else None
            )

        # Fallback for unexpected exceptions
        return cls.create(
            severity=SEVERITY_FATAL,
            code=ISSUE_CODE_EXCEPTION,
            diagnostics="An unexpected server error occurred."
        )

    @classmethod
    def from_pydantic_validation_error(cls, exc) -> OperationOutcome:
        """Create an OperationOutcome from a Pydantic ValidationError."""
        issues = []
        for error in exc.errors():
            loc = ".".join([str(x) for x in error.get("loc", [])])
            msg = error.get("msg", "Validation error")

            issues.append(OperationOutcomeIssue(
                severity=SEVERITY_ERROR,
                code=ISSUE_CODE_STRUCTURE,
                diagnostics=msg,
                expression=[loc] if loc else None
            ))

        return OperationOutcome(issue=issues)
