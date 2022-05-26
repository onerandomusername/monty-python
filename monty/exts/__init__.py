import pkgutil
from typing import Iterator

from monty.log import get_logger


__all__ = ("get_package_names",)

log = get_logger(__name__)


def get_package_names() -> Iterator[str]:
    """Iterate names of all packages located in /monty/exts/."""
    for package in pkgutil.iter_modules(__path__):
        if package.ispkg:
            yield package.name
