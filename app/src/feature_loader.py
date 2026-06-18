"""Dynamic feature discovery for `app.src.features` modules and packages."""
from __future__ import annotations

import importlib
import logging
import pkgutil
from collections.abc import Iterable

from . import features
from .models import FeatureSpec

logger = logging.getLogger(__name__)


def discover_features() -> list[FeatureSpec]:
    discovered: list[FeatureSpec] = []
    package_name = features.__name__
    for module_info in pkgutil.iter_modules(features.__path__):
        if module_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{package_name}.{module_info.name}")
        spec = None
        if hasattr(module, "get_feature"):
            spec = module.get_feature()
        elif hasattr(module, "FEATURE"):
            spec = module.FEATURE
        if spec is None:
            logger.debug("Feature module %s has no FEATURE/get_feature", module.__name__)
            continue
        if isinstance(spec, FeatureSpec):
            candidates: Iterable[FeatureSpec] = [spec]
        else:
            candidates = spec
        for candidate in candidates:
            if not isinstance(candidate, FeatureSpec):
                raise TypeError(f"{module.__name__} returned non-FeatureSpec: {type(candidate)!r}")
            if not candidate.enabled:
                logger.info("Feature disabled: %s", candidate.name)
                continue
            discovered.append(candidate)
    return discovered
