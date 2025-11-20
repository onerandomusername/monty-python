from typing import Final

import disnake
from disnake import Locale

from monty import constants
from monty.config import validators
from monty.config.models import Category, ConfigAttrMetadata, FreeResponseMetadata, SelectGroup, SelectOptionMetadata


__all__ = (
    "CATEGORY_TO_ATTR",
    "GROUP_TO_ATTR",
    "METADATA",
)


METADATA: Final[dict[str, ConfigAttrMetadata]] = dict(  # noqa: C408
    prefix=ConfigAttrMetadata(
        type=str,
        name="Command Prefix",
        description="The prefix used for text based commands.",
        requires_bot=True,
        categories={Category.General},
        modal=FreeResponseMetadata(button_label="Set Prefix", button_style=lambda x: disnake.ButtonStyle.green),
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
        validator=validators.validate_github_org,
        category=Category.GitHub,
        modal=FreeResponseMetadata(
            button_label="Edit Org",
            max_length=39,
            min_length=2,
        ),
    ),
    git_file_expansions=ConfigAttrMetadata(
        type=bool,
        category=Category.GitHub,
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


def _populate_group_to_attr() -> dict[SelectGroup, list[str]]:
    """Populate the GROUP_TO_ATTR mapping."""
    result = {}
    for attr, meta in METADATA.items():
        if meta.select_option:
            result.setdefault(meta.select_option.group, []).append(attr)
    return result


GROUP_TO_ATTR: Final[dict[SelectGroup, list[str]]] = _populate_group_to_attr()

CATEGORY_TO_ATTR: Final[dict[Category, list[str]]] = {
    cat: [attr for attr, meta in METADATA.items() if cat in meta.categories] for cat in Category
}
