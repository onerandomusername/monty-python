import datetime
from typing import TYPE_CHECKING, Any, Optional

import cachingutils
import cachingutils.redis


if TYPE_CHECKING:
    import redis.asyncio

    from ._cog import DocItem


WEEK_SECONDS = datetime.timedelta(weeks=1)


def item_key(item: "DocItem") -> str:
    """Get the redis redis key string from `item`."""
    return f"{item.package}:{item.relative_url_path.removesuffix('.html')}"


class DocRedisCache(cachingutils.redis.AsyncRedisCache):
    """Interface for redis functionality needed by the Doc cog."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._set_expires = set()
        self.namespace = self._prefix
        self._redis: redis.asyncio.Redis

    async def set(self, item: "DocItem", value: str) -> None:
        """
        Set the Markdown `value` for the symbol `item`.

        All keys from a single page are stored together, expiring a week after the first set.
        """
        redis_key = f"{self.namespace}:{item_key(item)}"
        needs_expire = False
        if redis_key not in self._set_expires:
            # An expire is only set if the key didn't exist before.
            # If this is the first time setting values for this key check if it exists and add it to
            # `_set_expires` to prevent redundant checks for subsequent uses with items from the same page.
            self._set_expires.add(redis_key)
            needs_expire = not await self._redis.exists(redis_key)

        await self._redis.hset(redis_key, item.symbol_id, value)  # pyright: ignore[reportGeneralTypeIssues]
        if needs_expire:
            await self._redis.expire(redis_key, WEEK_SECONDS)

    async def get(self, item: "DocItem", default: Any = None) -> Optional[str]:
        """Return the Markdown content of the symbol `item` if it exists."""
        res = await self._redis.hget(f"{self.namespace}:{item_key(item)}", item.symbol_id)  # pyright: ignore[reportGeneralTypeIssues]
        if res:
            return res.decode()
        return default

    async def delete(self, package: str) -> bool:
        """Remove all values for `package`; return True if at least one key was deleted, False otherwise."""
        connection = self._redis
        package_keys = [
            package_key async for package_key in connection.scan_iter(match=f"{self.namespace}:{package}:*")
        ]
        if package_keys:
            await connection.delete(*package_keys)
            return True
        return False


class StaleItemCounter(DocRedisCache):
    """Manage increment counters for stale `"DocItem"`s."""

    async def increment_for(self, item: "DocItem") -> int:
        """
        Increment the counter for `item` by 1, set it to expire in 3 weeks and return the new value.

        If the counter didn't exist, initialize it with 1.
        """
        key = f"{self.namespace}:{item_key(item)}:{item.symbol_id}"
        connection = self._redis
        await connection.expire(key, WEEK_SECONDS * 3)
        return int(await connection.incr(key))

    async def delete(self, package: str) -> bool:
        """Remove all values for `package`; return True if at least one key was deleted, False otherwise."""
        connection = self._redis
        package_keys = [
            package_key async for package_key in connection.scan_iter(match=f"{self.namespace}:{package}:*")
        ]
        if package_keys:
            await connection.delete(*package_keys)
            return True
        return False
