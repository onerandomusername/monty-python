# from pydantic import dataclasses
import dataclasses
import enum
import functools

import disnake

from monty.utils.code import prepare_input
from monty.utils.markdown import remove_codeblocks
from monty.utils.messages import extract_urls


class MontyEvent(enum.Enum):
    monty_message_processed = "monty_message_processed"


@dataclasses.dataclass(frozen=True)
class MessageContext:
    """A context for a message event."""

    content: str

    # Lazily initialize attributes
    @functools.cached_property
    def code(self) -> str | None:
        """Return the code blocks found in the message."""
        return prepare_input(self.content, require_fenced=True)

    @functools.cached_property
    def text(self) -> str:
        """Return the message content with code blocks removed."""
        return remove_codeblocks(self.content)

    @functools.cached_property
    def urls(self) -> list[str]:
        """Return the URLs found in the message."""
        return list(extract_urls(self.text))

    @classmethod
    def from_message_inter(
        cls, inter: disnake.MessageInteraction | disnake.MessageCommandInteraction, /
    ) -> "MessageContext":
        """Create a MessageContext from an interaction."""
        if isinstance(inter, disnake.MessageCommandInteraction):
            return cls(inter.target.content)
        return cls(inter.message.content)

    @classmethod
    def from_message(cls, message: disnake.Message) -> "MessageContext":
        """Create a MessageContext from a message."""
        return cls(content=message.content)
