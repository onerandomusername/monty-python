from __future__ import annotations

import socket
import sys
from typing import TYPE_CHECKING, Any, TypedDict

import aiohttp
from aiohttp_client_cache.backends.redis import RedisBackend as AiohttpRedisBackend
from aiohttp_client_cache.cache_control import CacheActions, ExpirationTime
from aiohttp_client_cache.session import CachedSession

from monty import constants
from monty.log import get_logger
from monty.utils import helpers


if TYPE_CHECKING:
    from collections.abc import Mapping
    from types import SimpleNamespace

    import redis.asyncio
    from aiohttp.tracing import TraceConfig
    from aiohttp.typedefs import StrOrURL

aiohttp_log = get_logger("monty.http")
cache_logger = get_logger("monty.http.caching")


class RevalidatingCacheActions(CacheActions):
    @classmethod
    def from_headers(cls, key: str, headers: Mapping):
        """Initialize from request headers."""
        res = super().from_headers(key, headers)
        res.revalidate = True
        return res


class RedisBackend(AiohttpRedisBackend):
    def create_cache_actions(
        self,
        key: str,
        url: StrOrURL,
        expire_after: ExpirationTime = None,
        refresh: bool = False,
        **kwargs,
    ) -> CacheActions:
        """
        Create cache actions based on request info.

        Args:
            key: key from create_key function
            url: Request URL
            expire_after: Expiration time to set only for this request; overrides
                ``CachedSession.expire_after``, and accepts all the same values.
            refresh: Revalidate with the server before using a cached response, and refresh if needed
                (e.g., a "soft refresh", like F5 in a browser)
            kwargs: All other request arguments
        """
        return CacheActions.from_request(
            key,
            url=url,
            request_expire_after=expire_after,
            refresh=refresh,
            session_expire_after=self.expire_after,
            urls_expire_after=self.urls_expire_after,
            cache_control=self.cache_control,
            cache_disabled=self.disabled,
            **kwargs,
        )


"""Create the aiohttp session and set the trace logger, if desired."""
trace_configs: list[TraceConfig] = []


async def _on_request_end(
    session: aiohttp.ClientSession,
    trace_config_ctx: SimpleNamespace,
    params: aiohttp.TraceRequestEndParams,
) -> None:
    """Log all aiohttp requests on request end."""
    resp = params.response
    aiohttp_log.info(
        "[{status!s} {reason!s}] {method!s} {url!s} ({content_type!s})".format(
            status=resp.status,
            reason=resp.reason or "None",
            method=params.method.upper(),
            url=params.url,
            content_type=resp.content_type,
        )
    )


class SessionArgs(TypedDict):
    proxy: str | None
    connector: aiohttp.BaseConnector


def session_args_for_proxy(proxy: str | None) -> SessionArgs:
    """Create a dict with `proxy` and `connector` items, to be passed to aiohttp.ClientSession."""
    connector = aiohttp.TCPConnector(
        resolver=aiohttp.AsyncResolver(),
        family=socket.AF_INET,
        ssl=(
            helpers._SSL_CONTEXT_UNVERIFIED
            if (proxy and proxy.startswith("http://"))
            else helpers._SSL_CONTEXT_VERIFIED
        ),
    )
    return {"proxy": proxy or None, "connector": connector}


def get_cache_backend(redis: redis.asyncio.Redis) -> RedisBackend:
    """Get the cache backend for aiohttp_client_cache."""
    return RedisBackend(
        constants.Client.config_prefix,
        "aiohttp_requests",
        expire_after=20,
        cache_control=True,
        connection=redis,
    )


class CachingClientSession(CachedSession):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.update(session_args_for_proxy(kwargs.get("proxy")))

        if "trace_configs" not in kwargs:
            trace_config = aiohttp.TraceConfig()
            trace_config.on_request_end.append(_on_request_end)
            trace_configs.append(trace_config)
            kwargs["trace_configs"] = trace_configs
        if "headers" not in kwargs:
            kwargs["headers"] = {
                "User-Agent": (
                    f"Python/{sys.version_info[0]}.{sys.version_info[1]} Monty-Python/{constants.Client.version} "
                    f"({constants.Client.git_repo})"
                ),
            }
        super().__init__(*args, **kwargs)
