"""Domain errors for EvalOps Kit."""

from __future__ import annotations


class EvalOpsError(Exception):
    """Base error type for user-facing CLI failures."""


class SuiteConfigError(EvalOpsError):
    """Raised when suite parsing or validation fails."""


class DatasetLoadError(EvalOpsError):
    """Raised when dataset loading or validation fails."""


class DiffError(EvalOpsError):
    """Raised when diff inputs or artifacts are invalid."""
