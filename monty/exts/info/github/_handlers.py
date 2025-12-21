"""Handlers for GitHub information classes."""

import dataclasses
import datetime
import enum
import re
from abc import abstractmethod
from typing import Generic, Literal, NamedTuple, TypeVar, cast, overload

import disnake
import disnake.utils
import ghretos
import githubkit
import githubkit.rest
import mistune
import yarl

from monty import constants
from monty.utils.markdown import DiscordRenderer

from . import graphql_models


T = TypeVar("T", bound=githubkit.GitHubModel)
V = TypeVar("V", bound=ghretos.GitHubResource)


class VisualStyleState(NamedTuple):
    emoji: constants.AppEmojiAnn
    colour: disnake.Colour


class RepoInfo(NamedTuple):
    """A shareable representation of a GitHub repository."""

    owner: str
    name: str

    @property
    def full_name(self) -> str:
        """Get the display name of the repository."""
        return f"{self.owner}/{self.name}"

    def __hash__(self) -> int:
        return hash((self.owner.lower(), self.name.lower()))


@dataclasses.dataclass
class ModelInfo(Generic[T]):
    """A shareable representation of a GitHub object."""

    # used for tiny and up
    emoji: disnake.Emoji | disnake.PartialEmoji
    title: str
    url: str
    number: int | None  # For issues, PRs, discussions
    ref: str | None  # For commits
    repo: RepoInfo | None
    # used for compact and up
    short_description_md: str
    # OGP and up
    created_at: datetime.datetime
    colour: disnake.Colour
    author_avatar_url: str | None
    author_name: str | None
    author_login: str | None
    data_source: T

    # TODO: figure out how to represent additional metadata like state, labels, etc.


class InfoSize(enum.Enum):
    """Sizes for GitHub info replacements."""

    TINY = enum.auto()  # One line of text with an icon
    COMPACT = enum.auto()  # Small 3 line info
    OGP = enum.auto()  # Replace GitHub's social media embed
    FULL = enum.auto()  # Full detailed information of all issue content


def titlize_issue(issue: githubkit.rest.Issue) -> str:
    if not issue.repository:
        return f"#{issue.number} {issue.title.strip()}"
    return f"{issue.repository.full_name}#{issue.number} {issue.title.strip()}"


def is_mannequin_user(
    user: githubkit.rest.SimpleUser
    | githubkit.rest.PublicUser
    | githubkit.rest.DiscussionPropUser
    | graphql_models.DiscussionCommentUser,
) -> bool:
    return bool(user.type and user.type.casefold() == "mannequin")


def get_user_display_name(
    user: githubkit.rest.SimpleUser
    | githubkit.rest.PublicUser
    | githubkit.rest.DiscussionPropUser
    | graphql_models.DiscussionCommentUser,
    *,
    include_login_alias: bool = False,
    include_html_url: bool = False,
    include_mannequin_tag: bool = True,
) -> str:
    name = user.name
    if is_mannequin_user(user) and user.html_url:
        # Workaround an API issue where in some cases login is a UUID for mannequins
        # and the display name is in the html_url
        # If the url points to ghost, the login value is good.
        name = yarl.URL(user.html_url).name
        if name == "ghost":
            name = None
        return (name or user.login) + (" (mannequin)" if include_mannequin_tag else "")
    user_string = name or user.login
    if include_html_url and user.html_url:
        user_string = f"[{user_string}](<{user.html_url}>)"
    if include_login_alias and name and name.casefold() != user.login.casefold():
        user_string += f" (`{user.login}`)"
    return user_string


def get_user_html_url(
    user: githubkit.rest.SimpleUser | githubkit.rest.DiscussionPropUser | graphql_models.DiscussionCommentUser,
) -> str | None:
    if is_mannequin_user(user):
        return None
    return user.html_url or None


class GitHubRenderer(Generic[T, V]):
    def __init__(self, *, limit: int | None = None) -> None:
        self._limit = limit

    @overload
    def render(self, obj: T, *, size: Literal[InfoSize.TINY], context: V) -> str: ...
    @overload
    def render(self, obj: T, *, size: Literal[InfoSize.COMPACT], context: V) -> str: ...
    @overload
    def render(self, obj: T, *, size: Literal[InfoSize.OGP], context: V) -> disnake.Embed: ...
    @overload
    def render(
        self, obj: T, *, size: Literal[InfoSize.FULL], context: V
    ) -> tuple[str, list[disnake.ui.TextDisplay]]: ...

    def render(
        self, obj: T, *, size: InfoSize, context: V
    ) -> str | disnake.ui.Container | disnake.Embed | tuple[str, list[disnake.ui.TextDisplay]]:
        """Render a GitHub object as a Disnake embed."""
        match size:
            case InfoSize.TINY:
                return self.render_tiny(obj, context=context)
            case InfoSize.COMPACT:
                return self.render_compact(obj, context=context)
            case InfoSize.OGP:
                return self.render_ogp(obj, context=context)
            case InfoSize.FULL:
                return self.render_full(obj, context=context)
            case _:
                msg = f"Unsupported size: {size}"
                raise ValueError(msg)

    def render_markdown(self, body: str, *, repo_url: str, limit: int = 2700) -> str:
        """Render GitHub Flavored Markdown to Discord flavoured markdown."""
        markdown = mistune.create_markdown(
            escape=False,
            renderer=DiscordRenderer(repo=repo_url),
            plugins=[
                "strikethrough",
                "url",
            ],
        )
        markdown.before_render_hooks.append(DiscordRenderer.hook_list_pre_render)

        # this will always be str, unless renderer above is set to None
        body = cast("str", markdown(body))

        body = body.strip()

        if len(body) > limit:
            return body[: limit - 3] + "..."

        return body

    @abstractmethod
    def render_tiny(self, obj: T, *, context: V) -> str:
        """Render a tiny version of the GitHub object."""
        raise NotImplementedError

    @abstractmethod
    def render_compact(self, obj: T, *, context: V) -> str:
        """Render a compact version of the GitHub object."""
        raise NotImplementedError

    @abstractmethod
    def render_ogp(self, obj: T, *, context: V) -> disnake.Embed:
        """Render an ogb replacement version of the GitHub object."""
        raise NotImplementedError

    @abstractmethod
    def render_ogp_cv2(self, obj: T, *, context: V) -> disnake.ui.Container:
        """Render an ogb replacement version of the GitHub object."""
        raise NotImplementedError

    @abstractmethod
    def render_full(self, obj: T, *, context: V) -> tuple[str, list[disnake.ui.TextDisplay]]:
        """Render a full version of the GitHub object."""
        raise NotImplementedError


# region: concrete renderers


class UserRenderer(GitHubRenderer[githubkit.rest.PublicUser, ghretos.User]):
    def render_tiny(
        self,
        obj: githubkit.rest.PublicUser,
        *,
        context: ghretos.User,
    ) -> str:
        return f"👤 [{obj.login}](<{obj.html_url}>)"

    def render_ogp(self, obj: githubkit.rest.PublicUser, *, context: ghretos.User) -> disnake.Embed:
        embed = disnake.Embed(
            title=f"`{obj.login}`'s GitHub profile info",
            description=f"```{obj.bio}```\n" if obj.bio else "",
            colour=disnake.Colour.blurple(),
            url=obj.html_url,
            timestamp=obj.created_at,
        )
        embed.set_thumbnail(url=obj.avatar_url)
        embed.set_footer(text="Account created at")

        if obj.type == "User":
            embed.add_field(
                name="Followers",
                value=f"[{obj.followers}]({obj.html_url}?tab=followers)",
                inline=True,
            )
            embed.add_field(
                name="Following",
                value=f"[{obj.following}]({obj.html_url}?tab=following)",
                inline=True,
            )
        elif obj.type == "Organization":
            embed.add_field(
                name="Followers",
                value=f"[{obj.followers}](https://github.com/orgs/{obj.login}/followerss)",
                inline=True,
            )

        embed.add_field(
            name="Public repos",
            value=f"[{obj.public_repos}]({obj.html_url}?tab=repositories)",
        )

        if obj.type == "User":
            embed.add_field(
                name="Gists",
                value=f"[{obj.public_gists}]({obj.html_url}/gists)",
            )

        if obj.blog:
            blog = obj.blog
            if not re.match(r"^https?:\/\/", blog):
                blog = f"https://{blog}"
            embed.add_field(name="Website", value=blog)

        return embed

    def render_ogp_cv2(self, obj: githubkit.rest.PublicUser, *, context: ghretos.User) -> disnake.ui.Container:
        container = disnake.ui.Container()
        text_display = disnake.ui.TextDisplay("")
        text_display.content = f"## [{obj.name or obj.login}](<{obj.html_url}>)\n\n"
        if obj.bio:
            text_display.content += f"{obj.bio}\n"
        container.children.append(text_display)
        section = disnake.ui.Section(accessory=disnake.ui.Thumbnail(obj.avatar_url))
        container.children.append(section)
        section.children.append(disnake.ui.TextDisplay(f"**Public Repos:** {obj.public_repos}"))
        section.children.append(disnake.ui.TextDisplay(f"**Followers:** {obj.followers}"))
        section.children.append(disnake.ui.TextDisplay(f"**Following:** {obj.following}"))

        return container

    def render_full(
        self,
        obj: githubkit.rest.PublicUser,
        *,
        context: ghretos.User,
    ) -> tuple[str, list[disnake.ui.TextDisplay]]:
        # For simplicity, we will just return the OGP embed as a text display
        text_display = disnake.ui.TextDisplay("")
        text_display.content = f"## [{obj.name}](<{obj.html_url}>)\n\n"
        if obj.bio:
            text_display.content += f"{obj.bio}\n"
        if obj.location:
            text_display.content += f"**Location:** {obj.location}\n"
        if obj.blog:
            text_display.content += f"**Blog:** {obj.blog}\n"
        if obj.company:
            text_display.content += f"**Company:** {obj.company}\n"
        text_display.content += f"**Public Repos:** {obj.public_repos}\n"
        text_display.content += f"**Followers:** {obj.followers}\n"
        text_display.content += f"**Following:** {obj.following}\n"
        return obj.name or obj.login, [text_display]


class RepoRenderer(
    GitHubRenderer[
        githubkit.rest.Repository | githubkit.rest.FullRepository | githubkit.rest.RepoSearchResultItem, ghretos.Repo
    ]
):
    def render_tiny(
        self,
        obj: githubkit.rest.Repository | githubkit.rest.FullRepository | githubkit.rest.RepoSearchResultItem,
        *,
        context: ghretos.Repo,
    ) -> str:
        return f"📦 [{obj.name}](<{obj.html_url}>)"

    def render_ogp(
        self,
        obj: githubkit.rest.Repository | githubkit.rest.FullRepository | githubkit.rest.RepoSearchResultItem,
        *,
        context: ghretos.Repo,
    ) -> disnake.Embed:
        html_url = obj.html_url
        description = obj.description or ""
        embed = disnake.Embed(
            title=obj.name,
            colour=disnake.Colour.blurple(),
            url=html_url,
        )

        # If it's a fork, then it will have a parent key
        if isinstance(obj, githubkit.rest.FullRepository) and obj.parent:
            parent = obj.parent
            description += f"\n\nForked from [{parent.full_name}]({parent.html_url})"

        if repo_owner := obj.owner:
            embed.set_author(
                name=repo_owner.login,
                url=repo_owner.html_url,
                icon_url=repo_owner.avatar_url,
            )

        repo_created_at = obj.created_at and obj.created_at.strftime("%d/%m/%Y")
        last_pushed = obj.pushed_at and obj.pushed_at.strftime("%d/%m/%Y at %H:%M")

        embed.set_footer(
            text=(
                f"{obj.forks_count} ⑂ "
                f"• {obj.stargazers_count} ⭐ "
                f"• Created At {repo_created_at} "
                f"• Last Commit {last_pushed}"
            )
        )

        # mirrors have a mirror_url key. See google/skia as an example.
        if obj.mirror_url:
            mirror_url = obj.mirror_url
            description += f"\n\nMirrored from <{mirror_url}>."

        embed.description = description

        return embed

    def render_ogp_cv2(
        self,
        obj: githubkit.rest.Repository | githubkit.rest.FullRepository | githubkit.rest.RepoSearchResultItem,
        *,
        context: ghretos.Repo,
    ) -> disnake.ui.Container:
        container = disnake.ui.Container()
        text_display = disnake.ui.TextDisplay("")
        text_display.content = f"## [{obj.name}](<{obj.html_url}>)\n\n"
        if obj.description:
            text_display.content += f"{obj.description}\n"
        container.children.append(text_display)
        if obj.owner:
            section = disnake.ui.Section(accessory=disnake.ui.Thumbnail(obj.owner.avatar_url))
        else:
            section = disnake.ui.Section(accessory=disnake.ui.Thumbnail(constants.Icons.github_avatar_url))
        container.children.append(section)
        section.children.append(disnake.ui.TextDisplay(f"**Stars:** {obj.stargazers_count}"))
        section.children.append(disnake.ui.TextDisplay(f"**Forks:** {obj.forks_count}"))
        section.children.append(disnake.ui.TextDisplay(f"**Open Issues:** {obj.open_issues_count}"))

        return container

    def render_full(
        self,
        obj: githubkit.rest.Repository | githubkit.rest.FullRepository | githubkit.rest.RepoSearchResultItem,
        *,
        context: ghretos.Repo,
    ) -> tuple[str, list[disnake.ui.TextDisplay]]:
        text_display = disnake.ui.TextDisplay("")
        text_display.content = f"## [{obj.full_name}](<{obj.html_url}>)\n\n"
        if obj.description:
            text_display.content += f"{obj.description}\n"
        text_display.content += f"**Stars:** {obj.stargazers_count}\n"
        text_display.content += f"**Forks:** {obj.forks_count}\n"
        text_display.content += f"**Open Issues:** {obj.open_issues_count}\n"
        text_display.content += f"**Watchers:** {obj.watchers_count}\n"
        return obj.full_name, [text_display]


class NumberableRenderer(
    GitHubRenderer[githubkit.rest.Issue | githubkit.rest.Discussion, ghretos.Issue | ghretos.NumberedResource]
):
    @staticmethod
    def _get_visual_style_state(obj: githubkit.rest.Issue | githubkit.rest.Discussion) -> VisualStyleState:
        if isinstance(obj, githubkit.rest.Discussion):
            # Discussions have locked as a valid state too
            # But state_reason only seems to appear if the discussion was ever closed
            # State_reason can be "resolved", "outdated", "duplicate", or "reopened"
            if obj.state_reason and obj.state_reason != "reopened":
                match obj.state_reason:
                    case "outdated":
                        emoji = constants.AppEmojis.discussion_outdated
                    case "resolved":
                        emoji = constants.AppEmojis.discussion_closed
                    case "duplicate":
                        emoji = constants.AppEmojis.discussion_duplicate
                    case _:
                        # This code is currently unreachable but future-proofs against new state reasons
                        emoji = constants.AppEmojis.discussion_closed_unresolved
            elif obj.answer_html_url is not None:
                emoji = constants.AppEmojis.discussion_answered
            elif obj.state == "open" or obj.state_reason == "reopened":
                emoji = constants.AppEmojis.discussion_generic
            else:
                # fall the emoji back to a state
                emoji = constants.AppEmojis.discussion_generic

            colour = disnake.Colour(emoji.color if isinstance(emoji, constants.Octicon) else constants.GHColour.default)

            return VisualStyleState(emoji=emoji, colour=colour)

        if obj.pull_request:
            if obj.pull_request.merged_at:
                emoji = constants.AppEmojis.pull_request_merged
            elif obj.state == "closed":
                emoji = constants.AppEmojis.pull_request_closed
            elif obj.draft is True:
                emoji = constants.AppEmojis.pull_request_draft
            elif obj.state == "open":
                emoji = constants.AppEmojis.pull_request_open
            else:
                # fall the emoji back to a state
                emoji = constants.AppEmojis.pull_request_open
        else:
            if obj.state == "closed":
                if obj.state_reason == "not_planned":
                    emoji = constants.AppEmojis.issue_closed_unplanned
                elif obj.state_reason == "duplicate":
                    emoji = constants.AppEmojis.issue_closed_duplicate
                elif obj.state_reason == "completed":
                    emoji = constants.AppEmojis.issue_closed_completed
                else:
                    emoji = constants.AppEmojis.issue_closed_generic
            elif obj.draft is True:
                emoji = constants.AppEmojis.issue_draft
            elif obj.state == "open":
                emoji = constants.AppEmojis.issue_open
            else:
                # fall the emoji back to a state
                emoji = constants.AppEmojis.issue_open

        colour = disnake.Colour(emoji.color if isinstance(emoji, constants.Octicon) else constants.GHColour.default)

        return VisualStyleState(emoji=emoji, colour=colour)

    def render_tiny(
        self,
        obj: githubkit.rest.Issue | githubkit.rest.Discussion,
        *,
        context: ghretos.Issue | ghretos.NumberedResource,
        include_owner: bool = True,
        include_repo: bool = True,
        include_resource_type: bool = False,
    ) -> str:
        emoji, _colour = self._get_visual_style_state(obj)
        if not include_resource_type:
            resource_type = ""
        elif isinstance(obj, githubkit.rest.Discussion):
            resource_type = "discussion"
        else:
            resource_type = "issue" if not obj.pull_request else "pull request"

        if resource_type:
            resource_type += " "

        name = ""
        if include_repo:
            if include_owner:
                name += f"{context.repo.owner}/"
            name += f"{context.repo.name}"
        name += f"#{obj.number}"

        text = f"{emoji} {resource_type.capitalize()}[`{name}` - {obj.title.strip()}](<{obj.html_url}>)"
        if obj.user:
            user_html_url = get_user_html_url(obj.user)
            if user_html_url:
                text += f" by [{get_user_display_name(obj.user)}](<{user_html_url}>)"
            else:
                text += f" by `{get_user_display_name(obj.user)}`"
        return text

    def render_compact(
        self,
        obj: githubkit.rest.Issue | githubkit.rest.Discussion,
        *,
        context: ghretos.Issue | ghretos.NumberedResource,
        include_owner: bool = True,
        include_repo: bool = True,
    ) -> str:
        emoji, _colour = self._get_visual_style_state(obj)
        content = f"## {emoji}"

        if include_repo:
            if include_owner:
                content += f"{context.repo.owner}/"
            content += f"{context.repo.name}"
        content += f"#{obj.number}"
        content += f" - [{obj.title.strip()}](<{obj.html_url}>)\n"

        if obj.user:
            content += "Authored by " + get_user_display_name(obj.user, include_html_url=True, include_login_alias=True)
            content += "\n"

        return content

    def render_ogp(
        self,
        obj: githubkit.rest.Issue | githubkit.rest.Discussion,
        *,
        context: ghretos.Issue | ghretos.NumberedResource,
    ) -> disnake.Embed:
        emoji, colour = self._get_visual_style_state(obj)
        embed = disnake.Embed(
            title=f"{emoji} [{context.repo.full_name}#{obj.number}] {obj.title.strip()}",
            url=obj.html_url,
            colour=colour,
            timestamp=obj.created_at,
        )

        if embed.title and len(embed.title) > 256:
            embed.title = embed.title[:255] + "\u2026"

        if obj.user:
            embed.set_author(
                name=get_user_display_name(obj.user, include_login_alias=True),
                url=get_user_html_url(obj.user),
                icon_url=obj.user.avatar_url,
            )

        if obj.body:
            body = self.render_markdown(obj.body, repo_url=context.repo.html_url, limit=self._limit or 350)
            embed.description = body
        else:
            embed.description = "*No description provided.*"

        embed.set_footer(text="Created", icon_url=constants.Icons.github_avatar_url)

        return embed

    def render_ogp_cv2(
        self,
        obj: githubkit.rest.Issue | githubkit.rest.Discussion,
        *,
        context: ghretos.Issue | ghretos.NumberedResource,
    ) -> disnake.ui.Container:
        emoji, colour = self._get_visual_style_state(obj)
        container = disnake.ui.Container()
        text_display = disnake.ui.TextDisplay("")
        text_display_added: bool = False
        container.accent_colour = colour
        text_display.content = (
            f"### {emoji} [[{context.repo.full_name}#{obj.number}] {obj.title.strip()}](<{obj.html_url}>)"
        )

        if obj.user:
            name = get_user_display_name(obj.user, include_login_alias=True, include_html_url=True)
            text_display.content += f"\n-# *Authored by {name}*\n"

            if obj.user.avatar_url:
                section = disnake.ui.Section(accessory=disnake.ui.Thumbnail(obj.user.avatar_url))
                section.children.append(text_display)
                container.children.append(section)
                text_display_added = True

        if obj.body:
            body = self.render_markdown(obj.body, repo_url=context.repo.html_url, limit=self._limit or 350)
            text_display.content += f"\n{body}\n"

        text_display.content += (
            "\n-# Created "
            # f"\n-# Created in [{context.repo.full_name}]({context.repo.html_url}) "
            f"at {disnake.utils.format_dt(obj.created_at, style='F')}"
        )
        if not text_display_added:
            container.children.append(text_display)

        return container

    def render_full(
        self,
        obj: githubkit.rest.Issue | githubkit.rest.Discussion,
        *,
        context: ghretos.Issue | ghretos.NumberedResource,
    ) -> tuple[str, list[disnake.ui.TextDisplay]]:
        old_limit = self._limit
        if not self._limit:
            self._limit = 3600
        try:
            cv2 = self.render_ogp_cv2(obj, context=context)
            return obj.title, [
                comp for comp in disnake.ui.walk_components([cv2]) if isinstance(comp, disnake.ui.TextDisplay)
            ]
        finally:
            self._limit = old_limit


class IssueCommentRenderer(
    GitHubRenderer[
        githubkit.rest.IssueComment | githubkit.rest.PullRequestReviewComment | graphql_models.DiscussionComment,
        ghretos.IssueComment
        | ghretos.PullRequestComment
        | ghretos.PullRequestReviewComment
        | ghretos.DiscussionComment,
    ]
):
    # TODO(onerandomusername): implement backlinks on issue/discussion/pull comments
    def _get_html_url(
        self,
        obj: githubkit.rest.IssueComment | githubkit.rest.PullRequestReviewComment | graphql_models.DiscussionComment,
        context: ghretos.IssueComment
        | ghretos.PullRequestComment
        | ghretos.PullRequestReviewComment
        | ghretos.DiscussionComment,
    ) -> str:
        if not isinstance(obj, githubkit.rest.PullRequestReviewComment):
            return obj.html_url

        if not isinstance(context, ghretos.PullRequestReviewComment):
            msg = "Mismatched context for PullRequestReviewComment"
            raise ValueError(msg)

        url = yarl.URL(obj.html_url)
        if context.files_page:
            return str((url / "files").with_fragment(f"r{context.comment_id}"))
        elif context.commit_page and context.sha:
            return str((url / "commits" / context.sha).with_fragment(f"r{obj.id}"))
        return obj.html_url

    def render_ogp(
        self,
        obj: githubkit.rest.IssueComment | githubkit.rest.PullRequestReviewComment | graphql_models.DiscussionComment,
        *,
        context: ghretos.IssueComment
        | ghretos.PullRequestComment
        | ghretos.PullRequestReviewComment
        | ghretos.DiscussionComment,
    ) -> disnake.Embed:
        if isinstance(obj, githubkit.rest.PullRequestReviewComment):
            colour = constants.GHColour.pull_comment
        else:
            colour = constants.GHColour.issue_comment
        embed = disnake.Embed(
            url=obj.html_url,
            colour=colour,
            description="",
            timestamp=obj.created_at,
        )

        if obj.user:
            embed.set_author(
                name=get_user_display_name(obj.user),
                url=get_user_html_url(obj.user),
                icon_url=obj.user.avatar_url,
            )

        if obj.body:
            body = self.render_markdown(obj.body, repo_url=context.repo.html_url, limit=350)
            embed.description = body
        else:
            embed.description = "*No description provided.*"

        embed.set_footer(text=f"Comment on {context.repo.full_name}#{context.number}")

        return embed


HANDLER_MAPPING: dict[type[ghretos.GitHubResource], type[GitHubRenderer]] = {
    # Autolinked objects
    ghretos.Issue: NumberableRenderer,
    ghretos.PullRequest: NumberableRenderer,
    ghretos.Discussion: NumberableRenderer,
    ghretos.NumberedResource: NumberableRenderer,
    ghretos.IssueComment: IssueCommentRenderer,
    ghretos.PullRequestComment: IssueCommentRenderer,
    ghretos.PullRequestReviewComment: IssueCommentRenderer,
    ghretos.DiscussionComment: IssueCommentRenderer,
    # Non-autolinked
    ghretos.User: UserRenderer,
    ghretos.Repo: RepoRenderer,
}

# GitHub supports url redirects on the frontend side for certain resources.
# This mapping defines which resources can be reached from other resources.
# This mapping only exists for validation AFTER fetching.
GITHUB_LINK_TRAVERSAL_EQUALS: dict[type[ghretos.GitHubResource], tuple[type[ghretos.GitHubResource], ...]] = {
    ghretos.Issue: (ghretos.Discussion, ghretos.Issue, ghretos.PullRequest),
    ghretos.PullRequest: (ghretos.Discussion, ghretos.Issue, ghretos.PullRequest),
    ghretos.Discussion: (ghretos.Issue, ghretos.Discussion, ghretos.PullRequest),
    ghretos.NumberedResource: (ghretos.Issue, ghretos.Discussion, ghretos.PullRequest),
    ghretos.IssueComment: (ghretos.IssueComment, ghretos.PullRequestComment),
    ghretos.PullRequestComment: (ghretos.IssueComment, ghretos.PullRequestComment),
}

# assert the mapping is correct
assert all(x in y for x, y in GITHUB_LINK_TRAVERSAL_EQUALS.items() if x is not ghretos.NumberedResource), (
    "Link traversal mapping is incomplete!"
)
