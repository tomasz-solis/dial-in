"""Tab render modules for the Dial In Streamlit app."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType

__all__ = ["closeout", "performance", "service", "setup", "today"]


def __getattr__(name: str) -> ModuleType:
    """Import view modules on first access."""

    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f"{__name__}.{name}")
    globals()[name] = module
    return module
