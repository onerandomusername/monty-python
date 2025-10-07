import enum
import re
from dataclasses import InitVar, dataclass, field
from typing import TYPE_CHECKING, Callable, Coroutine, Literal, Optional, Type, TypeVar, Union, cast

import aiohttp
import disnake
from disnake import Locale
from disnake.ext import commands

from monty import constants


if TYPE_CHECKING:
    from monty.bot import Monty


__all__ = ("METADATA",)

GITHUB_ORG_REGEX = re.compile(r"[a-zA-Z0-9\-]{1,}")

VALID_CONFIG_TYPES = Union[str, bool, float, int]
T = TypeVar("T", bound=VALID_CONFIG_TYPES)
AnyContext = Union[disnake.ApplicationCommandInteraction, commands.Context["Monty"]]

Localised = Union[str, dict[Locale | Literal["_"], str]]


async def validate_github_org(ctx: AnyContext, arg: str) -> Optional[str]:
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


@dataclass(kw_only=True, frozen=True)
class CategoryButtonMetadata:
    label: Localised
    style: disnake.ButtonStyle = disnake.ButtonStyle.grey


@dataclass(kw_only=True, frozen=True)
class CategoryMetadata:
    name: Localised
    description: Localised
    emoji: disnake.PartialEmoji | str
    button: CategoryButtonMetadata
    autocomplete_text: Localised


class Category(enum.Enum):
    General = CategoryMetadata(
        name="General",
        description="General bot configuration options.",
        emoji="⚙️",
        button=CategoryButtonMetadata(
            label="Edit General",
        ),
        autocomplete_text="General bot configuration",
    )
    GitHub = CategoryMetadata(
        name="GitHub Configuration",
        description="Configuration options for GitHub related features.",
        emoji="🐙",
        button=CategoryButtonMetadata(
            label="Edit Github",
        ),
        autocomplete_text="GitHub Configuration",
    )
    Python = CategoryMetadata(
        name="Python",
        description="Configuration options for Python related features.",
        emoji="🐍",
        button=CategoryButtonMetadata(
            label="Edit Python",
        ),
        autocomplete_text="Python tools",
    )


def get_category_choices() -> list[disnake.OptionChoice]:
    options = []
    for cat in Category:
        metadata: CategoryMetadata = cat.value
        default_name = (
            metadata.autocomplete_text
            if isinstance(metadata.autocomplete_text, str)
            else (metadata.autocomplete_text.get("_") or metadata.name)
        )
        assert isinstance(default_name, str)
        localised: disnake.Localized | str
        if isinstance(metadata.autocomplete_text, dict):
            data = metadata.autocomplete_text.copy()
            data.pop("_", default_name)
            data = cast("dict[disnake.Locale, str]", data)
            for opt, val in data.items():
                data[opt] = str(metadata.emoji) + " " + val
            localised = disnake.Localized(
                string=default_name,
                data=data,
            )
        else:
            localised = str(metadata.emoji) + " " + default_name
        options.append(disnake.OptionChoice(name=localised, value=cat.name))
    return options


@dataclass(kw_only=True, frozen=True)
class SelectMetadata:
    supertext: Localised | None = None
    description: Localised
    placeholder: Localised
    subtext: Localised | None = None


class SelectGroup(enum.Enum):
    GITHUB_EXPANSIONS = SelectMetadata(
        supertext="GitHub Expansions",
        description="Options for automatically expanding GitHub links, such as issues and specific lines in files.",
        placeholder="Select GitHub expansions to enable",
        subtext="Select none to disable all GitHub expansions.",
    )


@dataclass(kw_only=True, frozen=True)
class SelectOptionMetadata:
    group: SelectGroup
    description: Localised | None = None


@dataclass(kw_only=True, frozen=True)
class ButtonMetadata:
    label: Localised
    style: Callable[..., disnake.ButtonStyle] = lambda _: disnake.ButtonStyle.green


@dataclass(kw_only=True)
class ConfigAttrMetadata:
    name: Localised
    description: Localised
    type: Union[Type[str], Type[int], Type[float], Type[bool]]
    emoji: disnake.PartialEmoji | str | None = None
    category: InitVar[Category | None] = None
    categories: set[Category] | frozenset[Category] = field(default_factory=frozenset)
    select_option: Optional[SelectOptionMetadata] = None
    button: Optional[ButtonMetadata] = None
    requires_bot: bool = False
    long_description: Optional[str] = None
    depends_on_features: Optional[tuple[constants.Feature]] = None
    validator: Optional[Union[Callable, Callable[..., Coroutine]]] = None
    status_messages: StatusMessages = field(default_factory=StatusMessages)

    def __post_init__(self, category: Category | None) -> None:
        if not category and not self.categories:
            raise ValueError("Either category or categories must be provided")
        if category and self.categories:
            raise ValueError("Only one of category or categories can be provided")
        object.__setattr__(self, "categories", self.categories or frozenset({category}))

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
        requires_bot=True,
        categories={Category.General},
        button=ButtonMetadata(label="Set Prefix", style=lambda x: disnake.ButtonStyle.green),
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
        category=Category.GitHub,
        button=ButtonMetadata(label="Edit Org"),
    ),
    git_file_expansions=ConfigAttrMetadata(
        type=bool,
        categories={Category.GitHub, Category.General},
        name="GitHub/GitLab/BitBucket File Expansions",
        description="Whether to automatically expand links to specific lines for GitHub, GitLab, and BitBucket",
        long_description=(
            "Automatically expand links to specific lines for GitHub, GitLab, and BitBucket when possible."
        ),
        requires_bot=True,
        select_option=SelectOptionMetadata(
            group=SelectGroup.GITHUB_EXPANSIONS,
            description="github.com/<owner>/<repo>/blob/<branch>/<file>#L<line>",
        ),
        emoji="📄",
    ),
    github_issue_linking=ConfigAttrMetadata(
        type=bool,
        category=Category.GitHub,
        name="Issue Linking",
        description="Automatically link GitHub issues if they match the inline markdown syntax on GitHub.",
        long_description=(
            "Automatically link GitHub issues if they match the inline markdown syntax on GitHub. "
            "For example, `onerandomusername/monty-python#223` will provide a link to issue 223."
        ),
        select_option=SelectOptionMetadata(
            group=SelectGroup.GITHUB_EXPANSIONS,
            description="github.com/<owner>/<repo>/issues/<number>",
        ),
        requires_bot=True,
        emoji="🐛",
    ),
    github_comment_linking=ConfigAttrMetadata(
        type=bool,
        category=Category.GitHub,
        name="Comment Linking",
        depends_on_features=(constants.Feature.GITHUB_COMMENT_LINKS,),
        description="Automatically expand a GitHub comment link. Requires GitHub Issue Linking to have an effect.",
        requires_bot=True,
        select_option=SelectOptionMetadata(
            group=SelectGroup.GITHUB_EXPANSIONS,
            description="github.com/<owner>/<repo>/issues/<number>/#issuecomment-<number>",
        ),
        emoji="💬",
    ),
)


# check the config metadata is valid
def _check_config_metadata(metadata: dict[str, ConfigAttrMetadata]) -> None:
    for m in metadata.values():
        assert 0 < len(m.description) < 100
        assert m.button or m.select_option
        if m.select_option:
            assert isinstance(m.select_option, SelectOptionMetadata)
            assert m.type is bool
        if m.depends_on_features:
            for feature in m.depends_on_features:
                assert feature in constants.Feature


_check_config_metadata(METADATA)
