"""Handlers for GitHub information classes."""

import dataclasses
import datetime
import enum
from abc import abstractmethod
from typing import Generic, Literal, NamedTuple, TypeVar, overload

import disnake
import ghretos
import githubkit
import githubkit.rest

from monty import constants


T = TypeVar("T", bound=githubkit.GitHubModel)


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


class GitHubRenderer(Generic[T]):
    @overload
    def render(self, obj: T, *, size: Literal[InfoSize.TINY]) -> str: ...
    @overload
    def render(self, obj: T, *, size: Literal[InfoSize.COMPACT]) -> disnake.ui.Container: ...
    @overload
    def render(self, obj: T, *, size: Literal[InfoSize.OGP]) -> disnake.ui.Container: ...
    @overload
    def render(self, obj: T, *, size: Literal[InfoSize.FULL]) -> disnake.ui.Container: ...

    def render(self, obj: T, *, size: InfoSize) -> str | disnake.ui.Container:
        """Render a GitHub object as a Disnake embed."""
        match size:
            case InfoSize.TINY:
                return self.render_tiny(obj)
            case InfoSize.COMPACT:
                return self.render_compact(obj)
            case InfoSize.OGP:
                return self.render_ogp(obj)
            case InfoSize.FULL:
                return self.render_full(obj)
            case _:
                msg = f"Unsupported size: {size}"
                raise ValueError(msg)

    @abstractmethod
    def render_tiny(self, obj: T) -> str:
        """Render a tiny version of the GitHub object."""
        raise NotImplementedError

    @abstractmethod
    def render_compact(self, obj: T) -> str:
        """Render a compact version of the GitHub object."""
        raise NotImplementedError

    @abstractmethod
    def render_ogp(self, obj: T) -> disnake.ui.Container:
        """Render an ogb replacement version of the GitHub object."""
        raise NotImplementedError

    @abstractmethod
    def render_full(self, obj: T) -> disnake.ui.Container:
        """Render a full version of the GitHub object."""
        raise NotImplementedError


# region: concrete renderers


class IssueRenderer(GitHubRenderer[githubkit.rest.Issue]):
    @staticmethod
    def _get_visual_style_state(obj: githubkit.rest.Issue) -> VisualStyleState:
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

    def render_tiny(self, obj: githubkit.rest.Issue) -> str:
        emoji, _colour = self._get_visual_style_state(obj)
        return f"{emoji} Issue in {obj.repository.full_name if obj.repository else ''}#{obj.number} - [{obj.title}](<{obj.html_url}>)"

    def render_compact(self, obj: githubkit.rest.Issue, *, show_repo=True) -> str:
        emoji, _colour = self._get_visual_style_state(obj)
        content = f"{emoji}"

        if show_repo and obj.repository:
            content += f"{obj.repository.full_name}"
        content += f"#{obj.number}"
        content += f" - [{obj.title}](<{obj.html_url}>)\n"

        if obj.user:
            content += f"Authored by [{obj.user.name}](<{obj.user.html_url}>)"
            if obj.user.name and obj.user.login.casefold() != obj.user.name.casefold():
                content += f" (`{obj.user.login}`)"
            content += "\n"

        return content

    def render_ogp(self, obj: githubkit.rest.Issue) -> disnake.ui.Container:
        emoji, colour = self._get_visual_style_state(obj)
        container = disnake.ui.Container()
        container.accent_colour = colour
        content = f"{emoji} [{obj.title}](<{obj.html_url}>)"

        if obj.user:
            name = obj.user.name or obj.user.login
            content += f"\nAuthored by [{name}](<{obj.user.html_url}>)"
            if obj.user.name and obj.user.login.casefold() != name.casefold():
                content += f" (`{obj.user.login}`)"
            if obj.user.avatar_url:
                section = disnake.ui.Section(accessory=disnake.ui.Thumbnail(obj.user.avatar_url))
                section.children.append(disnake.ui.TextDisplay(content))
                container.children.append(section)
        return container


HANDLER_MAPPING: dict[type[ghretos.GitHubResource], type[GitHubRenderer]] = {
    ghretos.Issue: IssueRenderer,
}
