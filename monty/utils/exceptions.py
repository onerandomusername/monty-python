from typing import Optional

from disnake.ext.commands import CommandError


class APIError(CommandError):
    """Raised when an external API (eg. Wikipedia) returns an error response."""

    def __init__(self, api: str, status_code: int, error_msg: Optional[str] = None):
        super().__init__(error_msg)
        self.api = api
        self.status_code = status_code
        self.error_msg = error_msg
