from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING

import disnake
import disnake as dc

from monty import constants
from monty.exts.info.github.entities.cache import entity_cache
from monty.exts.info.github.models import Discussion, Issue, PullRequest
from monty.log import get_logger

from .resolution import resolve_entity_signatures


logger = get_logger(__name__)


def escape_special(x):
    return x


def format_diff_note(additions: int, deletions: int, changed_files: int) -> str | None:
    if not (changed_files and (additions or deletions)):
        return None  # Diff size unavailable
    return f"diff size: `+{additions}` `-{deletions}` ({changed_files} files changed)"


if TYPE_CHECKING:
    from monty.bot import Monty
    from monty.exts.info.github.models import Entity

ENTITY_TEMPLATE = "**{entity.kind} [#{entity.number}](<{entity.html_url}>):** {title}"


@dataclass(frozen=True, slots=True, kw_only=True)
class ProcessedMessage:
    item_count: int
    content: str = ""
    files: list[dc.File] = field(default_factory=list[dc.File])
    embeds: list[dc.Embed] = field(default_factory=list[dc.Embed])


def get_entity_emoji(bot: Monty, entity: Entity) -> str:
    if isinstance(entity, Issue):
        state = "open"
        if entity.closed:
            state = "closed_"
            state += "completed" if entity.state_reason == "completed" else "unplanned"
        emoji_name = "issue_" + state
    elif isinstance(entity, PullRequest):
        emoji_name = "pull_request_" + (
            "draft" if entity.draft
            else "merged" if entity.merged
            else "closed" if entity.closed
            else "open"
        )  # fmt: skip
    elif isinstance(entity, Discussion):
        emoji_name = "discussion"
        if entity.closed or entity.answered_by:
            emoji_name += (
                "_duplicate" if entity.state_reason == "DUPLICATE"
                else "_outdated" if entity.state_reason == "OUTDATED"
                else "_answered"
            )  # fmt: skip
    else:
        msg = f"Unknown entity type: {type(entity)}"
        raise TypeError(msg)

    try:
        return getattr(constants.Emojis, emoji_name)
    except AttributeError:
        logger.warning("No emoji found for entity state %s; using fallback", emoji_name)
        emoji_name = "github"

    return emoji_name


def _format_entity_detail(entity: Entity) -> str:
    if isinstance(entity, Issue):
        if not entity.labels:
            return ""
        if len(entity.labels) > 3:
            labels = entity.labels[:3]
            omission_note = f", and {len(entity.labels) - 3} more"
        else:
            labels, omission_note = entity.labels, ""
        body = f"labels: {', '.join(f'`{label}`' for label in labels)}{omission_note}"
    elif isinstance(entity, PullRequest):
        body = format_diff_note(entity.additions, entity.deletions, entity.changed_files)
        if body is None:
            return ""  # Diff size unavailable
    elif isinstance(entity, Discussion):
        if not entity.answered_by:
            return ""
        body = f"answered by {entity.answered_by.hyperlink}"
    else:
        msg = f"Unknown entity type: {type(entity)}"
        raise TypeError(msg)
    return f"-# {body}\n"


def _format_mention(bot: Monty, entity: Entity) -> str:
    headline = ENTITY_TEMPLATE.format(entity=entity, title=escape_special(entity.title))

    owner, name = entity.owner, entity.repo_name
    fmt_ts = partial(disnake.utils.format_dt, entity.created_at)
    subtext = (
        f"-# by {entity.user.hyperlink}"
        f" in [`{owner}/{name}`](<https://github.com/{owner}/{name}>)"
        f" on {fmt_ts('D')} ({fmt_ts('R')})\n"
    )
    entity_detail = _format_entity_detail(entity)

    emoji = get_entity_emoji(bot, entity)
    return f"{emoji} {headline}\n{subtext}{entity_detail}"


async def extract_entities(message: dc.Message) -> list[Entity]:
    matches = list(dict.fromkeys([r async for r in resolve_entity_signatures(message)]))
    cache_hits = await asyncio.gather(*(entity_cache.get(m) for m in matches), return_exceptions=True)
    return [entity for entity in cache_hits if entity and not isinstance(entity, BaseException)]


async def entity_message(bot: Monty, message: dc.Message) -> ProcessedMessage:
    entities = [_format_mention(bot, entity) for entity in await extract_entities(message)]

    if len("\n".join(entities)) > 2000:
        while len("\n".join(entities)) > 1970:  # Accounting for omission note
            entities.pop()
        entities.append("-# Some mentions were omitted")

    return ProcessedMessage(content="\n".join(dict.fromkeys(entities)), item_count=len(entities))
