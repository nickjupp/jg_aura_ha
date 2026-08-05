"""Load the component's pure-Python modules without importing Home Assistant.

`custom_components/jg_aura/__init__.py` pulls in homeassistant, which is not
installed here (and needs a newer interpreter than this sandbox has). api.py and
const.py are deliberately HA-free, so load them directly under a synthetic
package name -- that keeps their `from .const import ...` relative imports working.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "jg_aura"
PKG = "_jg_aura_under_test"


def _load() -> tuple[types.ModuleType, types.ModuleType]:
    if PKG not in sys.modules:
        pkg = types.ModuleType(PKG)
        pkg.__path__ = [str(COMPONENT)]  # type: ignore[attr-defined]
        sys.modules[PKG] = pkg
    for name in ("const", "api"):
        full = f"{PKG}.{name}"
        if full in sys.modules:
            continue
        spec = importlib.util.spec_from_file_location(full, COMPONENT / f"{name}.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[full] = module
        spec.loader.exec_module(module)
    return sys.modules[f"{PKG}.api"], sys.modules[f"{PKG}.const"]


api, const = _load()
