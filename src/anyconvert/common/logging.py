"""Configurable internal logger for anyconvert.

Provides zero-overhead logging facilities using the standard library logging module.
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

_LOGGER_ROOT_NAME = "anyconvert"
_DEFAULT_FORMAT = "[%(name)s] [%(levelname)s] %(message)s"
_DEBUG_FORMAT = "[%(asctime)s] [%(name)s] [%(levelname)s] (%(filename)s:%(lineno)d) %(message)s"


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Obtain a logger instance under the anyconvert namespace.

    Args:
        name: Optional sub-module name. If None, returns root anyconvert logger.

    Returns:
        logging.Logger: Logger instance.
    """
    if name is None or name == _LOGGER_ROOT_NAME:
        return logging.getLogger(_LOGGER_ROOT_NAME)
    if name.startswith(f"{_LOGGER_ROOT_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_LOGGER_ROOT_NAME}.{name}")


def configure_logging(
    level: int | str = logging.WARNING,
    verbose: bool = False,
    stream: Optional[sys.stdout.__class__] = None,  # type: ignore[name-defined]
) -> None:
    """Configure anyconvert logging handlers and formatters.

    Args:
        level: Base logging level (e.g. logging.INFO, logging.DEBUG).
        verbose: If True, sets level to DEBUG and enables detailed timestamp formatting.
        stream: Optional stream to output logs to. Defaults to sys.stderr.
    """
    target_stream = stream if stream is not None else sys.stderr
    effective_level = logging.DEBUG if verbose else level

    root_logger = logging.getLogger(_LOGGER_ROOT_NAME)
    root_logger.setLevel(effective_level)

    # Remove existing anyconvert handlers to prevent duplicate lines
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    fmt = _DEBUG_FORMAT if verbose else _DEFAULT_FORMAT
    formatter = logging.Formatter(fmt)

    handler = logging.StreamHandler(target_stream)
    handler.setLevel(effective_level)
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)


# Add a NullHandler by default so anyconvert is quiet by default
logging.getLogger(_LOGGER_ROOT_NAME).addHandler(logging.NullHandler())
