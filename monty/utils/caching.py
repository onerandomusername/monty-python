from __future__ import annotations

import asyncio
import contextlib
import datetime
import functools
from typing import TYPE_CHECKING, Any, AsyncGenerator, Callable, Coroutine, Optional, Tuple, Type, TypeVar, Union
from weakref import WeakValueDictionary

import cachingutils
import cachingutils.redis

from monty import constants
from monty.log import get_logger


if TYPE_CHECKING:
    from typing_extensions import ParamSpec

    P = ParamSpec("P")
    T = TypeVar("T")
    Coro = Coroutine[Any, Any, T]

KT = TypeVar("KT")
VT = TypeVar("VT")
UNSET = object()


# vendored from cachingutils, but as they're internal, they're put here in case they change
def _extend_posargs(sig: list[int], posargs: list[int], *args: Any) -> None:
    for i in posargs:
        val = args[i]

        hashed = hash(val)

        sig.append(hashed)


def _extend_kwargs(sig: list[int], _kwargs: list[str], allow_unset: bool = False, **kwargs: Any) -> None:
    for name in _kwargs:
        try:
            val = kwargs[name]
        except KeyError:
            if allow_unset:
                continue

            raise

        hashed = hash(val)

        sig.append(hashed)


def _get_sig(
    func: Callable[..., Any],
    args: Any,
    kwargs: Any,
    include_posargs: Optional[list[int]] = None,
    include_kwargs: Optional[list[str]] = None,
    allow_unset: bool = False,
) -> Tuple[int]:
    signature: list[int] = [id(func)]

    if include_posargs is not None:
        _extend_posargs(signature, include_posargs, *args)
    else:
        for arg in args:
            signature.append(hash(arg))

    if include_kwargs is not None:
        _extend_kwargs(signature, include_kwargs, allow_unset, **kwargs)
    else:
        for name, value in kwargs.items():
            signature.append(hash((name, value)))

    return tuple(signature)


def redis_cache(
    prefix: str,
    /,
    key_func: Any = None,
    skip_cache_func: Any = lambda *args, **kwargs: False,
    timeout: Optional[Union[int, float, datetime.timedelta]] = 60 * 60 * 24 * 7,
    include_posargs: Optional[list[int]] = None,
    include_kwargs: Optional[list[str]] = None,
    allow_unset: bool = False,
    cache_cls: Optional[Type[cachingutils.redis.AsyncRedisCache]] = None,
    cache: Any = None,
) -> Callable[[Callable[P, Coro[T]]], Callable[P, Coro[T]]]:
    """Decorate a function to cache its result in redis."""
    redis_cache = cachingutils.redis.async_session(constants.Client.config_prefix)
    if cache_cls:
        # we actually want to do it this way, as it is important that they are *actually* the same class
        if cache and type(cache_cls) is not type(cache):
            raise TypeError("cache cannot be provided if cache_cls is provided and cache and cache_cls are different")
        _cache: cachingutils.redis.AsyncRedisCache = cache_cls(session=redis_cache._redis)  # type: ignore
    else:
        _cache = redis_cache

    if isinstance(timeout, datetime.timedelta):
        timeout = int(timeout.total_seconds())
    elif isinstance(timeout, float):
        timeout = int(timeout)

    cache_logger = get_logger(__package__ + ".caching")

    prefix = prefix + ":"

    def decorator(func: Callable[P, Coro[T]]) -> Callable[P, Coro[T]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            if key_func is not None:
                if include_posargs is not None:
                    key_args = tuple(k for i, k in enumerate(args) if i in include_posargs)
                else:
                    key_args = args

                if include_kwargs is not None:
                    key_kwargs = {k: v for k, v in kwargs if k in include_kwargs}
                else:
                    key_kwargs = kwargs.copy()

                key = prefix + key_func(*key_args, **key_kwargs)

            else:
                key = prefix + str(
                    _get_sig(
                        func,
                        args,
                        kwargs,
                        include_posargs=include_posargs,
                        include_kwargs=include_kwargs,
                        allow_unset=allow_unset,
                    )
                )

            if not skip_cache_func(*args, **kwargs):
                value = await _cache.get(key, UNSET)

                if value is not UNSET:
                    if constants.Client.debug:
                        cache_logger.info("Cache hit on {key}".format(key=key))

                    return value

            result: T = await func(*args, **kwargs)

            await _cache.set(key, result, timeout=timeout)
            return result

        return wrapper

    return decorator


class RedisCache:
    def __init__(
        self,
        prefix: str,
        *,
        timeout: datetime.timedelta = datetime.timedelta(days=1),  # noqa: B008
    ) -> None:
        session = cachingutils.redis.async_session(constants.Client.redis_prefix)
        self._rediscache = cachingutils.redis.AsyncRedisCache(prefix=prefix.rstrip(":") + ":", session=session._redis)
        self._redis_timeout = timeout.total_seconds()
        self._locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    async def get(self, key: str, default: Optional[tuple[Optional[str], Any]] = None) -> Any:
        """
        Get the provided key from the internal caches.

        First position in the response is the ETag, if set, the second item is the contents.
        """
        return await self._rediscache.get(key, default=default)

    async def set(self, key: str, value: Any, *, timeout: Optional[float] = None) -> None:
        """Set the provided key and value into the internal caches."""
        return await self._rediscache.set(key, value=value, timeout=timeout or self._redis_timeout)

    @contextlib.asynccontextmanager
    async def lock(self, key: str) -> AsyncGenerator[None, None]:
        """Runs a lock with the provided key."""
        if key not in self._locks:
            lock = asyncio.Lock()
            self._locks[key] = lock
        else:
            lock = self._locks[key]

        async with lock:
            yield
