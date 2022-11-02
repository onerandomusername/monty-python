from __future__ import annotations

from typing import Hashable, Optional

from disnake.ext import commands


class APIError(commands.CommandError):
    """Raised when an external API (eg. Wikipedia) returns an error response."""

    def __init__(self, api: str, status_code: int, error_msg: Optional[str] = None) -> None:
        super().__init__(error_msg)
        self.api = api
        self.status_code = status_code
        self.error_msg = error_msg


class BotAccountRequired(commands.CheckFailure):
    """Raised when the bot needs to be in the guild."""

    def __init__(self, msg: str) -> None:
        self._error_title = "Bot Account Required"
        self.msg = msg

    def __str__(self) -> str:
        return self.msg


class FeatureDisabled(commands.CheckFailure):
    """Raised when a feature is attempted to be used that is currently disabled for that guild."""

    def __init__(self) -> None:
        super().__init__("This feature is currently disabled.")


class LockedResourceError(RuntimeError):
    """
    Exception raised when an operation is attempted on a locked resource.

    Attributes:
        `type` -- name of the locked resource's type
        `id` -- ID of the locked resource
    """

    def __init__(self, resource_type: str, resource_id: Hashable) -> None:
        self.type = resource_type
        self.id = resource_id

        super().__init__(
            f"Cannot operate on {self.type.lower()} `{self.id}`; "
            "it is currently locked and in use by another operation."
        )
