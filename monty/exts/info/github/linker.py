from __future__ import annotations

import asyncio
import datetime as dt
from contextlib import suppress
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, Self, final

import disnake
import disnake as dc
from typing_extensions import Any, override

from monty.log import get_logger


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
logger = get_logger(__name__)


class SafeView(dc.ui.View):
    @override
    async def on_error(self, *, interaction: dc.Interaction, error: Exception, item: dc.ui.Item[Any]) -> None:
        if interaction.response.is_done():
            await interaction.followup.send("Something went wrong :(", ephemeral=True)
        # else: don't complete interaction,
        # letting discord client send red error message


@dataclass(frozen=True, slots=True, kw_only=True)
class ProcessedMessage:
    item_count: int
    content: str = ""
    files: list[dc.File] = field(default_factory=list[dc.File])
    embeds: list[dc.Embed] = field(default_factory=list[dc.Embed])


async def remove_view_after_delay(message: dc.Message, delay: float = 30.0) -> None:
    logger.trace("waiting %ss to remove view of %s", delay, message)
    await asyncio.sleep(delay)
    with suppress(disnake.NotFound, disnake.HTTPException):
        logger.debug("removing view of %s", message)
        await message.edit(view=None)


@final
class MessageLinker:
    def __init__(self) -> None:
        self._refs: dict[dc.Message, dc.Message] = {}
        self._frozen = set[dc.Message]()

    @property
    def refs(self) -> MappingProxyType[dc.Message, dc.Message]:
        return MappingProxyType(self._refs)

    @property
    def expiry_threshold(self) -> dt.datetime:
        return dt.datetime.now(tz=dt.UTC) - dt.timedelta(hours=24)

    def freeze(self, message: dc.Message) -> None:
        logger.debug("freezing message %s", message)
        self._frozen.add(message)

    def unfreeze(self, message: dc.Message) -> None:
        logger.debug("unfreezing message %s", message)
        self._frozen.discard(message)

    def is_frozen(self, message: dc.Message) -> bool:
        return message in self._frozen

    def get(self, original: dc.Message) -> dc.Message | None:
        return self._refs.get(original)

    def free_dangling_links(self) -> None:
        # Saving keys to a tuple to avoid a "changed size during iteration" error
        for msg in tuple(self._refs):
            if msg.created_at < self.expiry_threshold:
                logger.trace("message {} is dangling; freeing", msg)
                self.unlink(msg)
                self.unfreeze(msg)

    def link(self, original: dc.Message, reply: dc.Message) -> None:
        logger.debug("linking %s to %s", original, reply)
        self.free_dangling_links()
        if original in self._refs:
            msg = f"message {original.id} already has a reply linked"
            raise ValueError(msg)
        self._refs[original] = reply

    def unlink(self, original: dc.Message) -> None:
        logger.debug("unlinking %s", original)
        self._refs.pop(original, None)

    def get_original_message(self, reply: dc.Message) -> dc.Message | None:
        return next((msg for msg, reply_ in self._refs.items() if reply == reply_), None)

    def unlink_from_reply(self, reply: dc.Message) -> None:
        if (original_message := self.get_original_message(reply)) is not None:
            self.unlink(original_message)

    def is_expired(self, message: dc.Message) -> bool:
        return message.created_at < self.expiry_threshold

    async def delete(self, message: dc.Message) -> None:
        if message.author.bot and (original := self.get_original_message(message)):
            logger.debug("reply %s deleted; unlinking original message %s", message, original)
            self.unlink(original)
            self.unfreeze(original)
        elif (reply := self.get(message)) and not self.is_frozen(message):
            if self.is_expired(message):
                logger.debug("message %s has expired; unlinking", message)
                self.unlink(message)
            else:
                logger.debug("deleting reply %s of message %s", reply, message)
                # We don't need to do any unlinking here because reply.delete() triggers
                # on_message_delete which runs the current hook again, and since replies
                # are bot messages, self.unlink(original) above handles it for us.
                await reply.delete()
        self.unfreeze(message)

    async def edit(
        self,
        before: dc.Message,
        after: dc.Message,
        *,
        message_processor: Callable[[dc.Message], Awaitable[ProcessedMessage]],
        interactor: Callable[[dc.Message], Awaitable[None]],
        view_type: Callable[[dc.Message, int], dc.ui.View],
        view_timeout: float = 30.0,
    ) -> None:
        if before.content == after.content:
            logger.trace("content did not change")
            return

        if self.is_expired(before):
            # The original message wasn't updated recently enough
            logger.debug("message %s has expired; unlinking", before)
            self.unlink(before)
            return

        old_output = await message_processor(before)
        new_output = await message_processor(after)
        if old_output == new_output:
            logger.trace("message changed but objects are the same")
            return

        logger.debug(
            "running edit hook for %s",
            getattr(message_processor, "__name__", message_processor),
        )

        if not (reply := self.get(before)):
            if self.is_frozen(before):
                logger.trace("skipping frozen message {}", before)
                return
            if old_output.item_count > 0:
                logger.trace(
                    "skipping message that was removed from the linker at some point "
                    "(most likely when the reply was deleted)"
                )
                return
            logger.debug("no objects were present before, treating as new message")
            await interactor(after)
            return

        if self.is_frozen(before):
            logger.trace("skipping frozen message {}", before)
            return

        # Some processors use negative values to symbolize special error values, so this
        # can't be `== 0`. An example of this is the snippet_message() function in the
        # file app/components/github_integration/code_links.py
        if new_output.item_count <= 0:
            logger.debug("all objects were edited out")
            self.unlink(before)
            await reply.delete()
            return

        logger.debug("editing message %s with updated objects", reply)
        await reply.edit(
            content=new_output.content,
            embeds=new_output.embeds,
            files=new_output.files,
            suppress_embeds=not new_output.embeds,
            view=view_type(after, new_output.item_count),
            allowed_mentions=dc.AllowedMentions.none(),
        )
        await remove_view_after_delay(reply, view_timeout)


class ItemActions(SafeView):
    linker: ClassVar[MessageLinker]
    action_singular: ClassVar[str]
    action_plural: ClassVar[str]
    message: dc.Message
    item_count: int

    def __init__(self, message: dc.Message, item_count: int) -> None:
        super().__init__()
        self.message = message
        self.item_count = item_count

    async def _reject_early(self, interaction: dc.Interaction, action: str) -> bool:
        assert interaction.guild
        if interaction.user.id == self.message.author.id or interaction.permissions.manage_messages:
            logger.trace(
                "%s run by %s who is the author or a mod",
                action,
                (interaction.user),
            )
            return False
        logger.debug(
            "%s run by %s who is not the author nor a mod",
            action,
            (interaction.user),
        )
        await interaction.response.send_message(
            "Only the person who "
            + (self.action_singular if self.item_count == 1 else self.action_plural)
            + f" can {action} this message.",
            ephemeral=True,
        )
        return True

    @dc.ui.button(label="Delete", emoji="❌")
    async def delete(self, interaction: dc.MessageInteraction, _: dc.ui.Button[Self]) -> None:
        logger.trace("delete button pressed on message {}", interaction.message)
        if await self._reject_early(interaction, "remove"):
            return
        await interaction.message.delete()

    @dc.ui.button(label="Freeze", emoji="❄️")  # test: allow-vs16
    async def freeze(self, interaction: dc.Interaction, button: dc.ui.Button[Self]) -> None:
        logger.trace("freeze button pressed on message {}", self.message)
        if await self._reject_early(interaction, "freeze"):
            return
        self.linker.freeze(self.message)
        button.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            "Message frozen. I will no longer react to what happens to your original message.",
            ephemeral=True,
        )
