"""Execution role enum."""

from enum import StrEnum


class Role(StrEnum):
    """Execution role assigned during the development workflow."""

    ARCHITECT = "ARCHITECT"
    SPEC = "SPEC"
    DEV = "DEV"
    TESTER = "TESTER"
    REVIEWER = "REVIEWER"
    INTEGRATOR = "INTEGRATOR"
