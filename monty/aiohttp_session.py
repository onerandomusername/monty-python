from __future__ import annotations

import datetime
import socket
import sys
from typing import TYPE_CHECKING, Any, TypedDict

import aiohttp
import httpx_aiohttp
from aiohttp_client_cache.backends.redis import RedisBackend
from aiohttp_client_cache.response import CachedResponse
from aiohttp_client_cache.session import CachedSession

from monty import constants
from monty.log import get_logger
from monty.utils import helpers
from monty.utils.services import update_github_ratelimits_on_request


if TYPE_CHECKING:
    from types import SimpleNamespace

    import redis.asyncio
    from aiohttp.tracing import TraceConfig

aiohttp_log = get_logger("monty.http")
cache_logger = get_logger("monty.http.caching")


async def _on_request_end(
    session: aiohttp.ClientSession,
    trace_config_ctx: SimpleNamespace,
    params: aiohttp.TraceRequestEndParams,
) -> None:
    """Log all aiohttp requests on request end.

    If the request was to api.github.com, update the github headers.
    """
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
    if resp.url.host == "api.github.com":
        update_github_ratelimits_on_request(resp)


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


def filter_caching(response: CachedResponse | aiohttp.ClientResponse) -> bool:
    """Filter function for aiohttp_client_cache to determine if a response should be cached."""
    # cache 404 and 410 for only two hours
    if not isinstance(response, CachedResponse):
        return True
    if response.status == 200:
        return True
    delta = datetime.datetime.utcnow() - response.created_at  # noqa: DTZ003
    match response.status:
        case 404:
            return delta <= datetime.timedelta(minutes=30)
        case 410:
            return delta <= datetime.timedelta(days=1)
    return True


def get_cache_backend(redis: redis.asyncio.Redis) -> RedisBackend:
    """Get the cache backend for aiohttp_client_cache."""
    return RedisBackend(
        constants.Client.config_prefix,
        "aiohttp_requests",
        # We default to revalidating, so this just prevents ballooning.
        expire_after=60 * 60 * 24 * 7,  # hold requests for one week.
        cache_control=True,
        allowed_codes=(200, 404, 410),
        connection=redis,
        filter_fn=filter_caching,
    )


class CachingClientSession(CachedSession):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Create the aiohttp session and set the trace logger, if desired."""
        kwargs.update(session_args_for_proxy(kwargs.get("proxy")))

        if "trace_configs" not in kwargs:
            trace_configs: list[TraceConfig] = []
            trace_config = aiohttp.TraceConfig()
            trace_config.on_request_end.append(_on_request_end)
            trace_configs.append(trace_config)
            kwargs["trace_configs"] = trace_configs
        if "headers" not in kwargs:
            kwargs["headers"] = {
                "User-Agent": (
                    f"Python/{sys.version_info[0]}.{sys.version_info[1]} Monty-Python/{constants.Client.git_ref} "
                    f"({constants.Client.git_repo})"
                ),
            }
        super().__init__(*args, **kwargs)

    async def _request(self, *args, **kwargs) -> CachedResponse:
        if "refresh" not in kwargs:
            kwargs["refresh"] = True
        return await super()._request(*args, **kwargs)


class AiohttpTransport(httpx_aiohttp.AiohttpTransport):
    async def aclose(self) -> None:
        """Override aclose to not do anything since we manage the underlying transport elsewhere."""

    async def close(self) -> None:
        """Override close to not do anything since we manage the underlying transport elsewhere."""
