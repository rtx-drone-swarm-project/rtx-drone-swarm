"""Dynamic search-algorithm registry.

Drop a module in this package with a ``BaseSearchAlgorithm`` subclass and it
will be available to mission start, benchmark validation, and frontend UI
metadata after backend restart. For stable API keys and good UI labels, set
``algorithm_key`` and ``display_name`` on the class.
"""

from __future__ import annotations

from backend.app.algorithms.base import BaseSearchAlgorithm
import importlib
import inspect
import logging
import pkgutil
import re
from dataclasses import dataclass
from typing import Dict, Type

from app.algorithms.base import BaseSearchAlgorithm


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlgorithmInfo:
    key: str
    label: str
    description: str | None
    module: str
    class_name: str
    display_order: int


_ALGORITHM_CLASSES: Dict[str, Type[BaseSearchAlgorithm]] = {}
_ALGORITHM_INFO: Dict[str, AlgorithmInfo] = {}


def _snake_case(value: str) -> str:
    value = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return value.replace("-", "_").lower()


def _label_from_key(key: str) -> str:
    return " ".join(part.upper() if part in {"apf", "aco"} else part.capitalize() for part in key.split("_"))


def discover_algorithms(force: bool = False) -> dict[str, Type[BaseSearchAlgorithm]]:
    """Import algorithm modules and register concrete strategy classes."""
    if _ALGORITHM_CLASSES and not force:
        return _ALGORITHM_CLASSES

    discovered: dict[str, Type[BaseSearchAlgorithm]] = {}
    info: dict[str, AlgorithmInfo] = {}

    for module_info in pkgutil.iter_modules(__path__):
        if module_info.name.startswith("_") or module_info.name == "base":
            continue
        module_name = f"{__name__}.{module_info.name}"
        try:
            module = importlib.import_module(module_name)
        except Exception:
            logger.exception("Failed to import algorithm module %s", module_name)
            continue

        for _, cls in inspect.getmembers(module, inspect.isclass):
            if cls is BaseSearchAlgorithm or not issubclass(cls, BaseSearchAlgorithm):
                continue
            if cls.__module__ != module.__name__:
                continue

            key = getattr(cls, "algorithm_key", None) or module_info.name
            key = str(key).strip()
            if not key:
                key = _snake_case(cls.__name__)
            if key in discovered:
                logger.warning(
                    "Duplicate algorithm key %r from %s.%s ignored; already registered by %s.%s",
                    key,
                    module.__name__,
                    cls.__name__,
                    discovered[key].__module__,
                    discovered[key].__name__,
                )
                continue

            label = getattr(cls, "display_name", None) or _label_from_key(key)
            discovered[key] = cls
            info[key] = AlgorithmInfo(
                key=key,
                label=str(label),
                description=getattr(cls, "description", None),
                module=module.__name__,
                class_name=cls.__name__,
                display_order=int(getattr(cls, "display_order", 100)),
            )

    if "voronoi" not in discovered:
        raise RuntimeError("Algorithm registry must include a 'voronoi' fallback")

    _ALGORITHM_CLASSES.clear()
    _ALGORITHM_CLASSES.update(dict[str, type[BaseSearchAlgorithm]](sorted(discovered.items())))
    _ALGORITHM_INFO.clear()
    _ALGORITHM_INFO.update(info)
    return _ALGORITHM_CLASSES


def get_algorithm(name: str) -> BaseSearchAlgorithm:
    """Return a new algorithm instance for this mission or benchmark run."""
    classes = discover_algorithms()
    cls = classes.get(name)
    if cls is None:
        logger.warning(
            "Unknown coverage algorithm %r; using voronoi. Valid keys: %s",
            name,
            sorted(classes.keys()),
        )
        cls = classes["voronoi"]
    return cls()


def list_algorithm_keys() -> list[str]:
    return [item["key"] for item in list_algorithms()]


def list_algorithms() -> list[dict[str, str | int | None]]:
    """Return API/UI metadata for every discovered algorithm."""
    discover_algorithms()
    return [
        {
            "key": item.key,
            "label": item.label,
            "description": item.description,
            "module": item.module,
            "class_name": item.class_name,
        }
        for item in sorted(_ALGORITHM_INFO.values(), key=lambda x: (x.display_order, x.label, x.key))
    ]


# Backward-compatibility export used by existing route validation/tests.
ALGORITHMS = discover_algorithms()
