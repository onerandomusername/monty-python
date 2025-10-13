from __future__ import annotations

import socket
import sys
from datetime import timedelta
from typing import TYPE_CHECKING, Any, TypedDict
from unittest.mock import Mock

import aiohttp
from multidict import CIMultiDict, CIMultiDictProxy

from monty import constants
from monty.log import get_logger
from monty.utils import helpers
from monty.utils.caching import RedisCache


if TYPE_CHECKING:
    from types import SimpleNamespace

    from aiohttp.tracing import TraceConfig

aiohttp_log = get_logger("monty.http")
cache_logger = get_logger("monty.http.caching")


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


class CachingClientSession(aiohttp.ClientSession):
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
        self.cache = RedisCache(
            "aiohttp_requests",
            timeout=timedelta(days=5),
        )

    async def _request(
        self,
        method: str,
        str_or_url: Any,
        use_cache: bool = True,
        **kwargs,
    ) -> aiohttp.ClientResponse:
        """Do the same thing as aiohttp does, but always cache the response."""
        method = method.upper().strip()
        cache_key = f"{method}:{str_or_url!s}"
        async with self.cache.lock(cache_key):
            cached = await self.cache.get(cache_key)
            if cached and use_cache:
                etag, body, resp_headers = cached
                if etag:
                    kwargs.setdefault("headers", {})["If-None-Match"] = etag
            else:
                etag = None
                body = None
                resp_headers = None

            r = await super()._request(method, str_or_url, **kwargs)
            if not use_cache:
                return r
            if r.status == 304:
                cache_logger.debug("HTTP Cache hit on %s", cache_key)
                # decode the original headers
                headers: CIMultiDict[str] = CIMultiDict()
                if resp_headers:
                    for key, value in resp_headers:
                        headers[key.decode()] = value.decode()
                r._cache["headers"] = r._headers = CIMultiDictProxy(headers)
                r.content = reader = aiohttp.StreamReader(
                    protocol=Mock(_reading_paused=False),
                    limit=len(body) if body else 0,
                )
                if body:
                    reader.feed_data(body)
                reader.feed_eof()
                r.status = 200
                return r

            etag = r.headers.get("ETag")
            # only cache if etag is provided and the request was in the 200
            if etag and 200 <= r.status < 300:
                body = await r.read()
                await self.cache.set(cache_key, (etag, body, r.raw_headers))
            return r
