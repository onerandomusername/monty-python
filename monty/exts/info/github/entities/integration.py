from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import suppress
from functools import partial
from itertools import chain
from typing import TYPE_CHECKING

import disnake
import disnake as dc
from disnake.ext import commands, tasks
from typing_extensions import final

from monty.exts.info.github.linker import ItemActions, MessageLinker, remove_view_after_delay
from monty.exts.info.github.models import Entity
from monty.utils.messages import suppress_embeds

from .cache import entity_cache
from .fmt import entity_message, extract_entities
from .resolution import ENTITY_REGEX


if TYPE_CHECKING:
    from monty.bot import Monty

IGNORED_MESSAGE_TYPES = frozenset(
    (
        dc.MessageType.thread_created,
        dc.MessageType.channel_name_change,
    )
)


@final
class EntityActions(ItemActions):
    action_singular = "mentioned this entity"
    action_plural = "mentioned these entities"


@final
class GitHubEntities(commands.Cog):
    def __init__(self, bot: Monty) -> None:
        self.bot = bot
        self.linker = MessageLinker()
        EntityActions.linker = self.linker

        self.update_recent_mentions.start()

    def cog_unload(self) -> None:
        self.update_recent_mentions.cancel()

    @tasks.loop(hours=1)
    async def update_recent_mentions(self) -> None:
        self.linker.free_dangling_links()
        entity_to_message_map = defaultdict[Entity, list[dc.Message]](list)

        # Gather all currently actively mentioned entities
        for msg in self.linker.refs:
            with suppress(dc.NotFound, dc.HTTPException):
                entities = await extract_entities(msg)
                for entity in entities:
                    entity_to_message_map[entity].append(msg)

        # Check which entities changed
        for entity in tuple(entity_to_message_map):
            key = (entity.owner, entity.repo_name, entity.number)
            await entity_cache.fetch(key)
            refreshed_entity = await entity_cache.get(key)
            if entity == refreshed_entity:
                entity_to_message_map.pop(entity)

        # Deduplicate remaining messages
        messages_to_update = set(chain.from_iterable(entity_to_message_map.values()))

        for msg in messages_to_update:
            reply = self.linker.get(msg)
            assert reply is not None

            new_output = await entity_message(self.bot, msg)

            with suppress(dc.NotFound, dc.HTTPException):
                await reply.edit(
                    content=new_output.content,
                    allowed_mentions=dc.AllowedMentions.none(),
                )

    @update_recent_mentions.before_loop
    async def before_update_recent_mentions(self) -> None:
        await self.bot.wait_until_ready()

    @commands.Cog.listener("on_message")
    async def reply_with_entities(self, message: disnake.Message) -> None:
        if not message.guild or message.guild.id not in (755868545279328417, 755083284416954428):
            return
        if (
            message.author.bot
            or message.type in IGNORED_MESSAGE_TYPES
            # or self.bot.fails_message_filters(message)
            or not ENTITY_REGEX.search(message.content)
        ):
            return

        if not message.guild:
            return

        output = await entity_message(self.bot, message)
        if not output.item_count:
            return

        sent_message = await message.reply(
            output.content,
            suppress_embeds=True,
            mention_author=False,
            allowed_mentions=dc.AllowedMentions.none(),
            view=EntityActions(message, output.item_count),
        )
        self.linker.link(message, sent_message)

        async with asyncio.TaskGroup() as group:
            group.create_task(remove_view_after_delay(sent_message))
            # The suppress is done here (instead of in resolve_repo_signatures) to
            # prevent blocking I/O for 5 seconds. The regex is run again here because
            # (1) modifying the signature of resolve_repo_signatures to accommodate that
            # would make it ugly (2) we can't modify entity_message's signature as the
            # hook system requires it to return a ProcessedMessage.
            if any(m["site"] for m in ENTITY_REGEX.finditer(message.content)):
                group.create_task(suppress_embeds(self.bot, message))

    @commands.Cog.listener()
    async def on_message_delete(self, message: dc.Message) -> None:
        await self.linker.delete(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: dc.Message, after: dc.Message) -> None:
        await self.linker.edit(
            before,
            after,
            message_processor=partial(entity_message, self.bot),
            interactor=self.reply_with_entities,
            view_type=EntityActions,
        )


def setup(bot: Monty) -> None:
    bot.add_cog(GitHubEntities(bot))
    entity_cache.gh = bot.github
