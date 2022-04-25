import logging
from typing import Optional

from disnake.ext import commands


log = logging.getLogger(__name__)


class InWhitelistCheckFailure(commands.CheckFailure):
    """Raised when the `in_whitelist` check fails."""

    def __init__(self, redirect_channel: Optional[int]) -> None:
        self.redirect_channel = redirect_channel

        if redirect_channel:
            redirect_message = f" here. Please use the <#{redirect_channel}> channel instead"
        else:
            redirect_message = ""

        error_message = f"You are not allowed to use that command{redirect_message}."

        super().__init__(error_message)


class BotAccountRequired(commands.CheckFailure):
    """Raised when the bot needs to be in the guild."""

    def __init__(self, msg: str):
        self._error_title = "Bot Account Required"
        self.msg = msg

    def __str__(self):
        return self.msg
