"""Typed role output contracts."""

from src.contracts.audit_report import (
    AuditReport,
    CiAuditFinding,
    SecurityRisk,
    SpecAuditFinding,
    TemplateMatch,
    UpgradeBacklogItem,
)
from src.contracts.escalation_report import (
    BlockTrigger,
    ErrorClass,
    EscalationReport,
    IterationAttempt,
    SpecContext,
    UnblockOption,
)

__all__ = [
    "AuditReport",
    "BlockTrigger",
    "CiAuditFinding",
    "ErrorClass",
    "EscalationReport",
    "IterationAttempt",
    "SecurityRisk",
    "SpecAuditFinding",
    "SpecContext",
    "TemplateMatch",
    "UnblockOption",
    "UpgradeBacklogItem",
]
