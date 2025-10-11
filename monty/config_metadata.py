from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeVar

import aiohttp
import disnake
from disnake import Locale
from disnake.ext import commands

from monty.constants import Feature


if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from monty.bot import Monty  # noqa: F401


__all__ = ("METADATA",)

GITHUB_ORG_REGEX = re.compile(r"[a-zA-Z0-9\-]{1,}")

VALID_CONFIG_TYPES = str | bool | float | int
T = TypeVar("T", bound=VALID_CONFIG_TYPES)
AnyContext = disnake.ApplicationCommandInteraction | commands.Context["Monty"]


async def validate_github_org(ctx: AnyContext, arg: str) -> str | None:
    """Validate all GitHub orgs meet GitHub's naming requirements."""
    if not arg:
        return None
    if not GITHUB_ORG_REGEX.fullmatch(arg):
        err = f"The GitHub org '{arg}' is not a valid GitHub organisation name."
        raise ValueError(err)

    try:
        r = await ctx.bot.http_session.head(f"https://github.com/{arg}", raise_for_status=True)
    except aiohttp.ClientResponseError:
        raise commands.UserInputError(
            "Organisation must be a valid GitHub user or organisation. Please check the provided account exists on"
            " GitHub and try again."
        ) from None
    else:
        r.close()
    return arg


@dataclass(kw_only=True)
class StatusMessages:
    set_attr_success: str = (  # this also can take an `old_setting` parameter
        "Successfully set `{name}`  to ``{new_setting}``."
    )
    set_attr_fail: str = "Could not change `{name}`: {err}"
    view_attr_success: str = "`{name}` is currently set to ``{current_setting}``."
    view_attr_success_unset: str = "`{name}` is currently unset."  # will take a current_setting parameter if needed
    clear_attr_success: str = "`{name}` has successfully been reset."
    clear_attr_success_with_default: str = "The `{name}` setting has been reset to ``{default}``."


@dataclass(kw_only=True)
class ConfigAttrMetadata:
    name: str | dict[Locale, str]
    description: str | dict[Locale, str]
    type: type[str | int | float | bool]
    requires_bot: bool = True
    long_description: str | None = None
    depends_on_features: tuple[str] | None = None
    validator: Callable | Callable[..., Coroutine] | None = None
    status_messages: StatusMessages = field(default_factory=StatusMessages)

    def __post_init__(self) -> None:
        if self.type not in (str, int, float, bool):
            raise ValueError("type must be one of str, int, float, or bool")
        if len(self.name) > 45:
            raise ValueError("name must be less than 45 characters")
        if len(self.description) > 100:
            raise ValueError("description must be less than 100 characters")


METADATA: dict[str, ConfigAttrMetadata] = dict(  # noqa: C408
    prefix=ConfigAttrMetadata(
        type=str,
        name="Command Prefix",
        description="The prefix used for text based commands.",
    ),
    github_issues_org=ConfigAttrMetadata(
        type=str,
        name={
            Locale.en_US: "GitHub Issue Organization",
            Locale.en_GB: "GitHub Issue Organisation",
        },
        description={
            Locale.en_US: "A specific organization or user to use as the default org for GitHub related commands.",
            Locale.en_GB: "A specific organisation or user to use as the default org for GitHub related commands.",
        },
        validator=validate_github_org,
    ),
    git_file_expansions=ConfigAttrMetadata(
        type=bool,
        name="GitHub/GitLab/BitBucket File Expansions",
        description="Whether to automatically expand links to specific lines for GitHub, GitLab, and BitBucket",
        long_description=(
            "Automatically expand links to specific lines for GitHub, GitLab, and BitBucket when possible."
        ),
    ),
    github_issue_linking=ConfigAttrMetadata(
        type=bool,
        name="GitHub Issue Linking",
        description="Automatically link GitHub issues if they match the inline markdown syntax on GitHub.",
        long_description=(
            "Automatically link GitHub issues if they match the inline markdown syntax on GitHub. "
            "For example, `onerandomusername/monty-python#223` will provide a link to issue 223."
        ),
    ),
    github_comment_linking=ConfigAttrMetadata(
        type=bool,
        name="GitHub Comment Linking",
        depends_on_features=(Feature.GITHUB_COMMENT_LINKS,),
        description="Automatically expand a GitHub comment link. Requires GitHub Issue Linking to have an effect.",
    ),
)


# check the config metadata is valid
def _check_config_metadata(metadata: dict[str, ConfigAttrMetadata]) -> None:
    for m in metadata.values():
        assert 0 < len(m.description) < 100


_check_config_metadata(METADATA)
