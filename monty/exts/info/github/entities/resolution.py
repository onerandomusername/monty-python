from __future__ import annotations

import re
from contextlib import suppress
from typing import TYPE_CHECKING

from githubkit.exception import RequestFailed
from typing_extensions import override

from .cache import TTRCache


if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    import disnake as dc

    EntitySignature = tuple[str, str, int]

ENTITY_REGEX = re.compile(
    r"(?P<site>\bhttps?://(?:www\.)?github\.com/)?"
    r"(?P<owner>\b[a-z0-9\-]+/)?"
    r"(?P<repo>\b[a-z0-9\-\._]+)?"
    r"(?P<sep>/(?:issues|pull|discussions)/|#)"
    r"(?P<number>\d{1,6})(?!\.\d|/?#)\b",
    re.IGNORECASE,
)


class OwnerCache(TTRCache[str, str]):
    @override
    async def fetch(self, key: str) -> None:
        with suppress(RequestFailed, RuntimeError):
            self[key] = await find_repo_owner(key)


owner_cache = OwnerCache(hours=1)


def remove_codeblocks(content: str) -> str:
    return content


async def find_repo_owner(name: str) -> str:
    resp = await gh.rest.search.async_repos(q=name, sort="stars", order="desc", per_page=20)
    return next(r.owner.login for r in resp.parsed_data.items if r.name == name and r.owner is not None)


async def resolve_repo_signature(owner: str | None, repo: str | None) -> tuple[str, str] | None:
    match owner, repo:
        case None, repo:
            # Only a name provided
            return None
        case owner, None:
            # Invalid case
            return None
        case owner, repo:
            return owner.rstrip("/"), repo


async def resolve_entity_signatures(
    message: dc.Message,
) -> AsyncGenerator[EntitySignature]:
    valid_signatures = 0
    for match in ENTITY_REGEX.finditer(remove_codeblocks(message.content)):
        site, sep = match["site"], match["sep"]
        # Ensure that the correct separator is used.
        if bool(site) == (sep == "#"):
            continue
        # NOTE: this *must* be after the previous check, as the number can be an empty
        # string if an incorrect separator was used, which would result in a ValueError
        # in the call to int().
        owner, repo, number = match["owner"], match["repo"], int(match["number"])
        if site:
            await message.edit(suppress_embeds=True)

        if owner is None:
            if repo is None and number < 10:
                # Ignore single-digit mentions like #1, (likely a false positive)
                continue
            if repo == "xkcd":
                # Ignore the xkcd prefix, as it is handled by xkcd_mentions.py
                continue

        if sig := await resolve_repo_signature(owner, repo):
            yield (*sig, number)
            valid_signatures += 1
            if valid_signatures == 10:
                break
