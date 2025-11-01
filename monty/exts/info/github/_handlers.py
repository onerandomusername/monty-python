"""Handlers for GitHub information classes."""

import dataclasses
import datetime
import enum
from abc import abstractmethod
from typing import Generic, Literal, NamedTuple, TypeVar, overload

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

GITHUB_COLOUR = disnake.Colour(0xFFFFFF)


class VisualStyleState(NamedTuple):
    emoji: str
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
        return f"#{issue.number} {issue.title}"
    return f"{issue.repository.full_name}#{issue.number} {issue.title}"


class GitHubRenderer(Generic[T, V]):
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
                "task_lists",
                "url",
            ],
        )
        body = markdown(body) or ""

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


class NumberableRenderer(
    GitHubRenderer[githubkit.rest.Issue | githubkit.rest.Discussion, ghretos.Issue | ghretos.NumberedResource]
):
    def __init__(self) -> None:
        super().__init__()
        self._limit = 350

    @staticmethod
    def _get_visual_style_state(obj: githubkit.rest.Issue | githubkit.rest.Discussion) -> VisualStyleState:
        if isinstance(obj, githubkit.rest.Discussion):
            if obj.answer_chosen_at:
                emoji = constants.Emojis.discussion_answered
                colour = constants.Colours.soft_green
            else:
                emoji = constants.Emojis.issue_draft
                colour = disnake.Colour.greyple()

            if not isinstance(colour, disnake.Colour):
                colour = disnake.Colour(colour)

            return VisualStyleState(emoji=emoji, colour=colour)
        if obj.pull_request:
            if obj.pull_request.merged_at:
                emoji = constants.Emojis.pull_request_merged
                colour = constants.Colours.purple
            elif obj.draft is True:
                emoji = constants.Emojis.pull_request_draft
                colour = disnake.Colour.greyple()
            elif obj.state == "open":
                emoji = constants.Emojis.pull_request_open
                colour = constants.Colours.soft_green
            elif obj.state == "closed":
                emoji = constants.Emojis.pull_request_closed
                colour = constants.Colours.soft_red
            else:
                # fall the emoji back to a state
                emoji = constants.Emojis.pull_request_open
                colour = constants.Colours.soft_green
        else:
            if obj.state == "closed":
                if obj.state_reason == "not_planned":
                    emoji = constants.Emojis.issue_closed_unplanned
                    colour = disnake.Colour.greyple()
                else:
                    emoji = constants.Emojis.issue_closed_completed
                    colour = constants.Colours.purple
            elif obj.draft is True:
                # not currently used by GitHub, but future planning
                emoji = constants.Emojis.issue_draft
                colour = disnake.Colour.greyple()
            elif obj.state == "open":
                emoji = constants.Emojis.issue_open
                colour = constants.Colours.soft_green

            else:
                # fall the emoji back to a state
                emoji = constants.Emojis.issue_open
                colour = constants.Colours.soft_green

        if not isinstance(colour, disnake.Colour):
            colour = disnake.Colour(colour)

        return VisualStyleState(emoji=emoji, colour=colour)

    def render_tiny(
        self,
        obj: githubkit.rest.Issue | githubkit.rest.Discussion,
        *,
        context: ghretos.Issue | ghretos.NumberedResource,
    ) -> str:
        emoji, _colour = self._get_visual_style_state(obj)
        if isinstance(obj, githubkit.rest.Discussion):
            resource_type = "discussion"
        else:
            resource_type = "issue" if not obj.pull_request else "pull request"
        text = (
            f"{emoji} {resource_type.capitalize()} [`{context.repo.full_name}#{obj.number}` - "
            f"{obj.title}](<{obj.html_url}>)"
        )
        if obj.user:
            text += f" by [{obj.user.name or obj.user.login}](<{obj.user.html_url}>)"
        return text

    def render_compact(
        self,
        obj: githubkit.rest.Issue | githubkit.rest.Discussion,
        *,
        context: ghretos.Issue | ghretos.NumberedResource,
    ) -> str:
        emoji, _colour = self._get_visual_style_state(obj)
        content = f"## {emoji}"

        content += f"{context.repo.full_name}"
        content += f"#{obj.number}"
        content += f" - [{obj.title}](<{obj.html_url}>)\n"

        if obj.user:
            content += f"Authored by [{obj.user.name}](<{obj.user.html_url}>)"
            if obj.user.name and obj.user.login.casefold() != obj.user.name.casefold():
                content += f" (`{obj.user.login}`)"
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
            title=f"{emoji} [{context.repo.full_name}#{obj.number}] {obj.title}",
            url=obj.html_url,
            colour=colour,
            timestamp=obj.created_at,
        )

        if obj.user:
            name = obj.user.name or obj.user.login
            embed.set_author(
                name=name,
                url=obj.user.html_url,
                icon_url=obj.user.avatar_url,
            )

        if obj.body:
            body = self.render_markdown(obj.body, repo_url=context.repo.html_url, limit=self._limit)
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
        text_display.content = f"### {emoji} [[{context.repo.full_name}#{obj.number}] {obj.title}](<{obj.html_url}>)"

        if obj.user:
            name = obj.user.name or obj.user.login
            text_display.content += f"\n-# *Authored by [{name}](<{obj.user.html_url}>)"
            if obj.user.name and obj.user.login.casefold() != name.casefold():
                text_display.content += f" (`{obj.user.login}`)"
            text_display.content += "*\n"
            if obj.user.avatar_url:
                section = disnake.ui.Section(accessory=disnake.ui.Thumbnail(obj.user.avatar_url))
                section.children.append(text_display)
                container.children.append(section)
                text_display_added = True

        if obj.body:
            body = self.render_markdown(obj.body, repo_url=context.repo.html_url, limit=self._limit)
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
        self._limit = 3700
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
        embed = disnake.Embed(
            url=obj.html_url,
            colour=GITHUB_COLOUR,
            description="",
            timestamp=obj.created_at,
        )

        if obj.user:
            name = obj.user.name or obj.user.login
            embed.set_author(
                name=name,
                url=obj.user.html_url,
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
    ghretos.Issue: NumberableRenderer,
    ghretos.PullRequest: NumberableRenderer,
    ghretos.Discussion: NumberableRenderer,
    ghretos.NumberedResource: NumberableRenderer,
    ghretos.IssueComment: IssueCommentRenderer,
    ghretos.PullRequestComment: IssueCommentRenderer,
    ghretos.PullRequestReviewComment: IssueCommentRenderer,
    ghretos.DiscussionComment: IssueCommentRenderer,
}
