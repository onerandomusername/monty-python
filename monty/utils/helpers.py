from __future__ import annotations

import asyncio
import datetime
import ssl
from typing import TYPE_CHECKING, Any, Coroutine, Optional, TypeVar, Union, overload
from urllib.parse import urlsplit, urlunsplit

import base65536
import dateutil.parser
import disnake
import yarl

from monty.log import get_logger
from monty.utils import scheduling
from monty.utils.messages import extract_urls


if TYPE_CHECKING:
    from typing_extensions import ParamSpec

    P = ParamSpec("P")
    T = TypeVar("T")
    Coro = Coroutine[Any, Any, T]
UNSET = object()

logger = get_logger(__name__)


def suppress_links(message: str) -> str:
    """Accepts a message that may contain links, suppresses them, and returns them."""
    for link in extract_urls(message):
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


def get_num_suffix(num: int) -> str:
    """Get the suffix for the provided number. Currently a lazy implementation so this only supports 1-20."""
    if num == 1:
        suffix = "st"
    elif num == 2:
        suffix = "nd"
    elif num == 3:
        suffix = "rd"
    elif 4 <= num < 20:
        suffix = "th"
    else:
        err = "num must be within 1-20. If you receive this error you should refactor the get_num_suffix method."
        raise RuntimeError(err)
    return suffix


def has_lines(string: str, count: int) -> bool:
    """Return True if `string` has at least `count` lines."""
    # Benchmarks show this is significantly faster than using str.count("\n") or a for loop & break.
    split = string.split("\n", count - 1)

    # Make sure the last part isn't empty, which would happen if there was a final newline.
    return bool(split[-1]) and len(split) == count


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
        return scheduling.create_task(inter.response.defer(**options))

    async def internal_task() -> None:
        now = loop.time()
        await asyncio.sleep(delay - (start - now))

        if inter.response.is_done():
            return
        try:
            await inter.response.defer(**options)
        except disnake.HTTPException as e:
            if e.code == 40060:  # interaction has already been acked
                logger.warning("interaction was already responded to (race condition)")
                return
            raise e

    start = loop.time()
    return scheduling.create_task(internal_task())


def utcnow() -> datetime.datetime:
    """Return the current time as an aware datetime in UTC."""
    return datetime.datetime.now(datetime.timezone.utc)


def fromisoformat(timestamp: str) -> datetime.datetime:
    """Parse the given ISO-8601 timestamp to an aware datetime object, assuming UTC if timestamp contains no timezone."""  # noqa: E501
    dt = dateutil.parser.isoparse(timestamp)
    if not dt.tzinfo:
        # assume UTC if naive datetime
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def ssl_create_default_context() -> ssl.SSLContext:
    """Return an ssl context that CloudFlare shouldn't flag."""
    ssl_context = ssl.create_default_context()
    ssl_context.post_handshake_auth = True
    return ssl_context


@overload
def get_invite_link_from_app_info(
    app_info: disnake.AppInfo,
    *,
    default_permissions: None = None,
) -> str | dict[int, str]: ...


@overload
def get_invite_link_from_app_info(
    app_info: disnake.AppInfo,
    *,
    guild_id: int = None,
    default_permissions: disnake.Permissions = None,
) -> str | None: ...


def get_invite_link_from_app_info(
    app_info: disnake.AppInfo,
    *,
    guild_id: int = None,
    default_permissions: disnake.Permissions = None,
) -> str | dict[int, str] | None:
    """Get an invite link from the provided disnake.AppInfo object."""
    urls: dict[int, yarl.URL] | None = {}
    # shortcut this mess with custom_install_urls...
    if app_info.custom_install_url:
        return str(app_info.custom_install_url)

    if default_permissions is None:
        default_permissions = disnake.Permissions(
            view_channel=True,
            send_messages=True,
            embed_links=True,
            attach_files=True,
            send_polls=True,
            send_messages_in_threads=True,
        )

    # this bit of the API is a bit of a mess, so let's try to cover all the cases
    # if a bot has the user and guild install types SET, then they can be installed either way,
    # but might not have an in-app invite
    # in this configuration a link that works for both is preferred but not installable
    # if a bot has only guild installs, then we can provide a guild invite link
    # if a bot has only user installs, then we can provide a user invite link
    # as of now, bots cannot have neither
    # the interesting case is when a bot has no discord provided url.
    # In this case we have to fall back to a possible invite value

    # The entire flow is as follows:
    # - If a custom install url is provided, use that.
    # - If both user and guild install types are available:
    #   - check for install_params in either config
    #     - if either has install_params, return a Discord Provided URL
    #     - else, return both user and guild oauth urls in a dict
    # - If only guild installs or only user installs are available:
    #   - check for install_params in the respective config
    #     - if present, use its permissions for the oauth url if provided (else no permissions)
    #     - if not present, this is NOT a discord provided URL
    #       - fall back to a fallback creation
    # a discord provided url matches the case of user or guild install type config having install_params
    # if either of them have install_params, then we can assume a discord provided url exists

    # HOWEVER
    # if the `guild_id` param is provided, we can only return a guild invite link,
    # therefore we don't even check user installations

    if not guild_id and any(
        (g and g.install_params) for g in (app_info.user_install_type_config, app_info.guild_install_type_config)
    ):
        return str(yarl.URL("https://discord.com/oauth2/authorize").with_query(client_id=app_info.id))

    params = {}
    params["client_id"] = app_info.id
    if app_info.redirect_uris and app_info.redirect_uris[0]:
        params["redirect_uri"] = app_info.redirect_uris[0]

    if app_info.user_install_type_config and not guild_id:
        params["scopes"] = ("applications.commands",)
        params["integration_type"] = disnake.ApplicationInstallTypes.user.flag

        if app_info.user_install_type_config.install_params:
            params["scopes"] = app_info.user_install_type_config.install_params.scopes

        urls[disnake.ApplicationInstallTypes.user.flag] = yarl.URL(
            disnake.utils.oauth_url(
                **params,
            )
        )

    if app_info.guild_install_type_config:
        if guild_id:
            params["guild"] = disnake.Object(id=guild_id)
        if default_permissions:
            params["permissions"] = default_permissions
        params["integration_type"] = disnake.ApplicationInstallTypes.guild.flag

        if app_info.guild_install_type_config.install_params:
            params["scopes"] = app_info.guild_install_type_config.install_params.scopes
            params["permissions"] = app_info.guild_install_type_config.install_params.permissions or default_permissions

        urls[disnake.ApplicationInstallTypes.guild.flag] = yarl.URL(
            disnake.utils.oauth_url(
                **params,
            )
        )

    if len(urls) == 1:
        return str(next(iter(urls.values())))
    if len(urls) == 0:
        return None
    return {k: str(v) for k, v in urls.items()}
