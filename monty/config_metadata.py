import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Optional, Type, TypeVar, Union

import aiohttp
import disnake
from disnake import Locale
from disnake.ext import commands


if TYPE_CHECKING:
    from monty.bot import Monty


__all__ = ("METADATA",)

GITHUB_ORG_REGEX = re.compile(r"[a-zA-Z0-9\-]{1,}")

VALID_CONFIG_TYPES = Union[str, bool, float, int]
T = TypeVar("T", bound=VALID_CONFIG_TYPES)
AnyContext = Union[disnake.ApplicationCommandInteraction, commands.Context["Monty"]]


async def validate_github_org(ctx: AnyContext, arg: T) -> Optional[T]:
    """Validate all GitHub orgs meet GitHub's naming requirements."""
    if not arg:
        return None
    if not GITHUB_ORG_REGEX.fullmatch(arg):
        err = f"The GitHub org '{arg}' is not a valid GitHub organisation name."
        raise ValueError(err)
    from monty.exts.backend.guild_config import GITHUB_REQUEST_HEADERS

    try:
        r = await ctx.bot.http_session.head(
            f"https://github.com/{arg}", headers=GITHUB_REQUEST_HEADERS, raise_for_status=True
        )
    except aiohttp.ClientResponseError:
        raise commands.UserInputError(
            "Organisation must be a valid GitHub user or Organsation. Please check the provided account exists on"
            " GitHub and try again."
        ) from None
    else:
        r.close()
    return arg


@dataclass(
    kw_only=True,
)
class StatusMessages:
    set_attr_success: str = "Successfully changed the `{name}` setting from ``{old_setting}`` to ``{new_setting}``."
    set_attr_fail: str = "Failed to change the `{name}` setting: {err}"
    view_attr_success: str = "`{name}` is currently set to ``{current_setting}.``"
    clear_attr_success: str = "The `{name}` setting has successfully been cleared."
    clear_attr_success_with_default: str = "The `{name}` setting has been set to the default of ``{default}``."


@dataclass(kw_only=True)
class ConfigAttrMetadata:
    name: Union[str, dict[Locale, str]]
    description: Union[str, dict[Locale, str]]
    type: Union[Type[str], Type[int], Type[float], Type[bool]]
    requires_bot: bool = True
    long_description: Optional[str] = None
    validator: Optional[Union[Callable, Callable[Any, Coroutine]]] = None
    status_messages: StatusMessages = StatusMessages()

    def __post_init__(self):
        if self.type not in (str, int, float, bool):
            raise ValueError("type must be one of str, int, float, or bool")


METADATA: dict[str, ConfigAttrMetadata] = dict(  # noqa: C408
    prefix=ConfigAttrMetadata(
        type=str,
        name="Command Prefix",
        description="The prefix used for getting ",
    ),
    github_issues_org=ConfigAttrMetadata(
        type=str,
        name={
            Locale.en_US: "GitHub Issue Organization",
            Locale.en_GB: "Github Issue Organisation",
        },
        description={
            Locale.en_US: "A specific organization or user to use as the default org for GitHub related commands.",
            Locale.en_GB: "A specific organisation or user to use as the default org for GitHub related commands.",
        },
        validator=validate_github_org,
    ),
)
