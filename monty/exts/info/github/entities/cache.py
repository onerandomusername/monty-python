from __future__ import annotations

import datetime as dt
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from githubkit.exception import RequestFailed
from typing_extensions import override

from monty.exts.info.github.models import Entity, Issue, PullRequest

from .discussions import get_discussion


if TYPE_CHECKING:
    from githubkit import GitHub, TokenAuthStrategy

logger = logging.getLogger(__name__)
EntitySignature = tuple[str, str, int]


class TTRCache[KT, VT](ABC):
    _ttr: dt.timedelta

    def __init__(self, **ttr: float) -> None:
        """Keyword arguments are passed to datetime.timedelta."""
        self._ttr = dt.timedelta(**ttr)
        self._cache: dict[KT, tuple[dt.datetime, VT]] = {}

    def __contains__(self, key: KT) -> bool:
        return key in self._cache

    def __getitem__(self, key: KT) -> tuple[dt.datetime, VT]:
        return self._cache[key]

    def __setitem__(self, key: KT, value: VT) -> None:
        self._cache[key] = (dt.datetime.now(tz=dt.UTC), value)

    @abstractmethod
    async def fetch(self, key: KT) -> None:
        pass

    async def _refresh(self, key: KT) -> None:
        if key not in self:
            logger.debug("%s not in cache; fetching", key)
            await self.fetch(key)
            return
        timestamp, *_ = self[key]
        if dt.datetime.now(tz=dt.UTC) - timestamp >= self._ttr:
            logger.debug("refreshing outdated key %s", key)
            await self.fetch(key)

    async def get(self, key: KT) -> VT | None:
        await self._refresh(key)
        try:
            _, value = self[key]
        except KeyError:
            return None
        return value


class EntityCache(TTRCache[EntitySignature, Entity]):
    def __init__(self, gh: GitHub[TokenAuthStrategy], **ttr: float) -> None:
        super().__init__(**ttr)
        self.gh: GitHub[TokenAuthStrategy] = gh

    @override
    async def fetch(self, key: EntitySignature) -> None:
        try:
            entity = (await self.gh.rest.issues.async_get(*key)).parsed_data
            model = Issue
            if entity.pull_request:
                entity = (await self.gh.rest.pulls.async_get(*key)).parsed_data
                model = PullRequest
            self[key] = model.model_validate(entity, from_attributes=True)
        except RequestFailed:
            if discussion := await get_discussion(self.gh, *key):
                self[key] = discussion


entity_cache = EntityCache(None, minutes=30)  # type: ignore[assignment]
