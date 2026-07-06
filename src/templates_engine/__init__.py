"""Template plugin discovery and validation (EXG-TPL-01/02)."""

from src.templates_engine.plugin_contract import (
    BootstrapContext,
    TemplateContractError,
    TemplateKind,
    TemplateMetadata,
    TemplatePlugin,
    validate_plugin,
)
from src.templates_engine.registry import TemplateRegistry

__all__ = [
    "BootstrapContext",
    "TemplateContractError",
    "TemplateKind",
    "TemplateMetadata",
    "TemplatePlugin",
    "TemplateRegistry",
    "validate_plugin",
]
