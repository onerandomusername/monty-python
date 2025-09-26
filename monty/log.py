# pyright: strict
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Mapping, TypedDict, cast

from monty import constants


if TYPE_CHECKING:
    from typing_extensions import Unpack


try:
    from rich.logging import RichHandler
except ImportError:
    RichHandler = None

TRACE = 5


def get_logger(name: str) -> "MontyLogger":
    """Stub method for logging.getLogger."""
    return cast("MontyLogger", logging.getLogger(name))


class LoggingParams(TypedDict, total=False):
    """Parameters for logging setup."""

    exc_info: logging._ExcInfoType  # type: ignore
    stack_info: bool
    stacklevel: int
    extra: Mapping[str, object] | None


class MontyLogger(logging.Logger):
    """Custom logger which implements the trace level."""

    def trace(self, msg: object, *args: object, **kwargs: Unpack[LoggingParams]) -> None:
        """
        Log 'msg % args' with severity 'TRACE'.

        To pass exception information, use the keyword argument exc_info with a true value, e.g.
        logger.trace("Houston, we have a %s", "tiny detail.", exc_info=1)
        """
        if self.isEnabledFor(TRACE):
            self._log(TRACE, msg, args, **kwargs)


def setup() -> None:
    """Set up loggers."""
    # Configure the "TRACE" logging level (e.g. "log.trace(message)")
    logging.TRACE = TRACE  # type: ignore
    logging.addLevelName(TRACE, "TRACE")
    logging.setLoggerClass(MontyLogger)

    format_string = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
    log_format = logging.Formatter(format_string)
    root_logger = logging.getLogger()

    # Set up file logging
    log_file = Path("logs/monty-python.log")
    log_file.parent.mkdir(exist_ok=True)

    # we use a rotating sized log handler for local development.
    # in production, we log each day's logs to a new file and delete it after 14 days
    if constants.Monitoring.log_mode == "daily":
        file_handler = logging.handlers.TimedRotatingFileHandler(
            log_file,
            "midnight",
            utc=True,
            backupCount=14,
            encoding="utf-8",
        )
    else:
        # File handler rotates logs every 5 MB
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=5 * (2**20),
            backupCount=10,
            encoding="utf-8",
        )
    file_handler.setFormatter(log_format)
    root_logger.addHandler(file_handler)

    if RichHandler is not None:
        rich_handler = RichHandler(rich_tracebacks=True)
        # rich_handler.setFormatter(log_format)
        root_logger.addHandler(rich_handler)
    else:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(log_format)
        root_logger.addHandler(console_handler)

    root_logger.setLevel(logging.DEBUG if constants.Monitoring.debug_logging else logging.INFO)
    # Silence irrelevant loggers
    logging.getLogger("disnake").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("cachingutils").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.DEBUG)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.INFO)
    logging.getLogger("gql.dsl").setLevel(logging.INFO)
    logging.getLogger("gql.transport.aiohttp").setLevel(logging.INFO)
    _set_trace_loggers()

    root_logger.info("Logging initialization complete")


def _set_trace_loggers() -> None:
    """
    Set loggers to the trace level according to the value from the BOT_TRACE_LOGGERS env var.

    When the env var is a list of logger names delimited by a comma,
    each of the listed loggers will be set to the trace level.

    If this list is prefixed with a "!", all of the loggers except the listed ones will be set to the trace level.

    Otherwise if the env var begins with a "*",
    the root logger is set to the trace level and other contents are ignored.
    """
    level_filter = constants.Monitoring.trace_loggers
    if level_filter:
        if level_filter.startswith("*"):
            logging.getLogger().setLevel(TRACE)

        elif level_filter.startswith("!"):
            logging.getLogger().setLevel(TRACE)
            for logger_name in level_filter.strip("!,").split(","):
                logging.getLogger(logger_name.strip()).setLevel(logging.DEBUG)

        else:
            for logger_name in level_filter.strip(",").split(","):
                logging.getLogger(logger_name.strip()).setLevel(TRACE)
