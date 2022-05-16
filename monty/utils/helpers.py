from __future__ import annotations

import asyncio
import datetime
import functools
import logging
import re
from typing import TYPE_CHECKING, Any, Callable, Optional, Tuple, Type, TypeVar, Union
from urllib.parse import urlsplit, urlunsplit

import base65536
import cachingutils
import cachingutils.redis
import disnake

from monty import constants


if TYPE_CHECKING:
    from typing_extensions import ParamSpec

    P = ParamSpec("P")
    T = TypeVar("T")
UNSET = object()


def suppress_links(message: str) -> str:
    """Accepts a message that may contain links, suppresses them, and returns them."""
    for link in set(re.findall(r"https?://[^\s]+", message, re.IGNORECASE)):
        message = message.replace(link, f"<{link}>")
    return message


def find_nth_occurrence(string: str, substring: str, n: int) -> Optional[int]:
    """Return index of `n`th occurrence of `substring` in `string`, or None if not found."""
    index = 0
    for _ in range(n):
        index = string.find(substring, index + 1)
        if index == -1:
            return None
    return index


def has_lines(string: str, count: int) -> bool:
    """Return True if `string` has at least `count` lines."""
    # Benchmarks show this is significantly faster than using str.count("\n") or a for loop & break.
    split = string.split("\n", count - 1)

    # Make sure the last part isn't empty, which would happen if there was a final newline.
    return split[-1] and len(split) == count


def pad_base64(data: str) -> str:
    """Return base64 `data` with padding characters to ensure its length is a multiple of 4."""
    return data + "=" * (-len(data) % 4)


EXPAND_BUTTON_PREFIX = "ghexp-v1:"


def encode_github_link(link: str) -> str:
    """Encode a github link with base 65536."""
    scheme, netloc, path, query, fragment = urlsplit(link)
    user, repo, literal_blob, blob, file_path = path.lstrip("/").split("/", 4)
    data = f"{user}/{repo}/{blob}/{file_path}#{fragment}"

    encoded = base65536.encode(data.encode())
    end_result = EXPAND_BUTTON_PREFIX + encoded
    assert link == decode_github_link(end_result), f"{link} != {decode_github_link(end_result)}"
    return end_result


def decode_github_link(compressed: str) -> str:
    """Decode a GitHub link that was encoded with `encode_github_link`."""
    compressed = compressed.removeprefix(EXPAND_BUTTON_PREFIX)
    # compressed = compressed.encode()
    data = base65536.decode(compressed).decode()

    if "#" in data:
        path, fragment = data.rsplit("#", 1)
    else:
        path, fragment = data, ""
    user, repo, blob, file_path = path.split("/", 3)
    path = f"{user}/{repo}/blob/{blob}/{file_path}"
    return urlunsplit(("https", "github.com", path, "", fragment))


def maybe_defer(inter: disnake.Interaction, *, delay: Union[float, int] = 2.0, **options) -> asyncio.Task:
    """Defer an interaction if it has not been responded to after ``delay`` seconds."""
    loop = inter.bot.loop
    if delay <= 0:
        return loop.create_task(inter.response.defer(**options))

    async def internal_task() -> None:
        now = loop.time()
        await asyncio.sleep(delay - (start - now))

        if inter.response.is_done():
            return
        await inter.response.defer(**options)

    start = loop.time()
    return loop.create_task(internal_task())


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

    if include_posargs:
        _extend_posargs(signature, include_posargs, *args)
    else:
        for arg in args:
            signature.append(hash(arg))

    if include_kwargs:
        _extend_kwargs(signature, include_kwargs, allow_unset, **kwargs)
    else:
        for name, value in kwargs.items():
            signature.append(hash((name, value)))

    return tuple(signature)


# caching
def redis_cache(
    prefix: str,
    key_func: Any = None,
    /,
    skip_cache_func: Any = lambda *args, **kwargs: False,
    timeout: Optional[Union[int, float, datetime.timedelta]] = 60 * 60 * 24 * 7,
    include_first_arg: bool = False,
    cache_cls: Optional[Type[cachingutils.redis.AsyncRedisCache]] = None,
    cache: Any = None,
    **kwargs,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorate a function to cache its result in redis."""
    redis_cache = cachingutils.redis.async_session(constants.Client.config_prefix)
    if cache_cls:
        # we actually want to do it this way, as it is important that they are *actually* the same class
        if cache and type(cache_cls) is not type(cache):
            raise TypeError("cache cannot be provided if cache_cls is provided and cache and cache_cls are different")
        _cache: cachingutils.redis.AsyncRedisCache = cache_cls(session=redis_cache._redis)
    else:
        _cache = redis_cache

    if timeout:
        if isinstance(timeout, datetime.timedelta):
            timeout = int(timeout.total_seconds())
        elif isinstance(timeout, float):
            timeout = int(timeout)

    cache_logger = logging.getLogger(__package__ + ".caching")

    prefix = prefix + ":"

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            if not include_first_arg:
                key_args = args[1:]
            else:
                key_args = args
            if key_func:
                key = prefix + key_func(*key_args, **kwargs)
            else:
                key = prefix + str(_get_sig(func, key_args, kwargs))

            if not skip_cache_func(*key_args, **kwargs):
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
