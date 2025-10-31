import base64
import enum
import itertools
import random
import re
from dataclasses import dataclass
from datetime import timezone
from typing import Any, NamedTuple
from urllib.parse import quote_plus

import attrs
import cachingutils
import disnake
import ghretos
import githubkit
import githubkit.exception
import mistune
import msgpack
import yarl
from disnake.ext import commands

import monty.utils.services
from monty import constants
from monty.bot import Monty
from monty.constants import Feature
from monty.errors import MontyCommandError
from monty.events import MessageContext, MontyEvent
from monty.log import get_logger
from monty.utils import responses, scheduling
from monty.utils.extensions import invoke_help_command
from monty.utils.helpers import fromisoformat, get_num_suffix, suppress_links
from monty.utils.markdown import DiscordRenderer, remove_codeblocks
from monty.utils.messages import DeleteButton, extract_urls, suppress_embeds

from . import _handlers as github_handlers


# Maximum number of issues in one message
MAXIMUM_ISSUES = 6


EXPAND_ISSUE_CUSTOM_ID_PREFIX = "gh:issue-expand-v2:"
EXPAND_ISSUE_CUSTOM_ID_FORMAT = EXPAND_ISSUE_CUSTOM_ID_PREFIX + r"{user_id}:{state}:{org}/{repo}#{num}"
EXPAND_ISSUE_CUSTOM_ID_REGEX = re.compile(
    re.escape(EXPAND_ISSUE_CUSTOM_ID_PREFIX)
    # 1 is expanded, 0 is collapsed
    + r"(?P<user_id>[0-9]+):(?P<current_state>0|1):"
    r"(?P<org>[a-zA-Z0-9][a-zA-Z0-9\-]{1,39})\/(?P<repo>[\w\-\.]{1,100})#(?P<number>[0-9]+)"
)

DISCUSSION_COMMENT_GRAPHQL_QUERY = """
    query getDiscussionComment($id: ID!) {
        node(id: $id) {
            ... on DiscussionComment {
                id
                html_url: url
                body
                created_at: createdAt
                user: author {
                    login
                    html_url: url
                    avatar_url: avatarUrl
                }
            }
        }
    }
"""


log = get_logger(__name__)


class RenderContext(NamedTuple):
    """Context provided to the rendering method."""

    user: str
    repo: str | None = None

    @property
    def html_url(self) -> str:
        """Provide the html_url to whatever this ends up targetting."""
        url = f"https://github.com/{self.user}/"
        if self.repo:
            url += f"{self.repo}/"
        return url


class GithubInfo(
    commands.Cog,
    name="GitHub Information",
    slash_command_attrs={
        "context": disnake.InteractionContextTypes(guild=True),
        "install_types": disnake.ApplicationInstallTypes(guild=True),
    },
):
    """Fetches info from GitHub."""

    def __init__(self, bot: Monty) -> None:
        self.bot = bot

        self.autolink_cache: cachingutils.MemoryCache[int, tuple[disnake.Message, list[ghretos.GitHubResource]]] = (
            cachingutils.MemoryCache(timeout=600)
        )

    async def cog_load(self) -> None:
        """
        Run initial fetch commands upon loading.

        Sync the Ratelimit object, and more.
        Fetch the graphQL schema from GitHub.
        """
        await self._fetch_and_update_ratelimits()

    async def _fetch_and_update_ratelimits(self) -> None:
        async with self.bot.http_session.disabled():  # do not cache this endpoint
            r = await self.bot.github.rest.rate_limit.async_get()
        data = r.json()
        monty.utils.services.update_github_ratelimits_from_ratelimit_page(data)

    def render_github_markdown(self, body: str, *, context: RenderContext | None = None, limit: int = 2700) -> str:
        """Render GitHub Flavored Markdown to Discord flavoured markdown."""
        url_prefix = context and context.html_url
        markdown = mistune.create_markdown(
            escape=False,
            renderer=DiscordRenderer(repo=url_prefix),
            plugins=[
                "strikethrough",
                "task_lists",
                "url",
            ],
        )
        body = markdown(body) or ""

        if len(body) > limit:
            return body[: limit - 3] + "..."

        return body

    async def fetch_resource(self, obj: ghretos.GitHubResource) -> githubkit.GitHubModel | None:
        """Fetch a GitHub resource."""
        if type(obj) is ghretos.Issue:
            r = await self.bot.github.rest.issues.async_get(
                owner=obj.repo.owner,
                repo=obj.repo.name,
                issue_number=obj.number,
            )
            return r.parsed_data
        if type(obj) is ghretos.PullRequest:
            r = await self.bot.github.rest.pulls.async_get(
                owner=obj.repo.owner,
                repo=obj.repo.name,
                pull_number=obj.number,
            )
            return r.parsed_data

        return None  # Type is not yet supported

    # @github_group.command(name="ratelimit", aliases=("rl",), hidden=True)

    @commands.is_owner()
    async def ratelimits_command(self, ctx: commands.Context, refresh: bool = False) -> None:
        """Check the current RateLimits connected to GitHub."""
        embed = disnake.Embed(title="GitHub Ratelimits")
        if refresh:
            await self._fetch_and_update_ratelimits()

        use_inline = len(monty.utils.services.GITHUB_RATELIMITS) <= 18  # 25 fields, 3 per line, 1 for the seperator.
        for i, (resource_name, rate_limit) in enumerate(monty.utils.services.GITHUB_RATELIMITS.items()):
            embed_value = ""
            for name, value in attrs.asdict(rate_limit).items():
                embed_value += f"**`{name}`**: {value}\n"
            embed.add_field(name=resource_name, value=embed_value, inline=use_inline)

            # add a "newline" after every 3 fields
            if use_inline and i % 3 == 2:
                embed.add_field("", "", inline=False)

        if len(embed.fields) == 0 or random.randint(0, 3) == 0:
            embed.set_footer(text="GitHub moment.")
        await ctx.send(
            embed=embed,
            components=DeleteButton(allow_manage_messages=False, initial_message=ctx.message, user=ctx.author),
        )

    @commands.Cog.listener("on_" + MontyEvent.monty_message_processed.value)
    async def on_message_automatic_issue_link(
        self,
        message: disnake.Message | disnake.ApplicationCommandInteraction,
        context: MessageContext,
    ) -> None:
        """
        Automatic issue linking.

        Listener to retrieve issue(s) from a GitHub repository using automatic linking if matching <org>/<repo>#<issue>.
        """
        matches = []
        for url in context.urls:
            match = ghretos.parse_url(url)
            if match is not None and isinstance(match, ghretos.Issue):
                matches.append(match)

        if not matches:
            return

        if len(matches) > MAXIMUM_ISSUES:
            if isinstance(message, disnake.Message):
                await message.add_reaction(constants.Emojis.decline)
            elif isinstance(message, disnake.ApplicationCommandInteraction):
                await message.response.send_message(
                    content=f"{constants.Emojis.decline} Too many issues found in message to "
                    f"display (maximum {MAXIMUM_ISSUES}).",
                    ephemeral=True,
                )
            return

        components: list = []
        for match in matches:
            # premptively check supported types:
            handler = github_handlers.HANDLER_MAPPING.get(type(match))
            if handler is None:
                continue
            resource_data = await self.fetch_resource(match)
            if resource_data is None:
                continue

            components.append(handler().render_ogp(resource_data))

        if not components:
            return
        components.append(
            disnake.ui.ActionRow(
                DeleteButton(
                    allow_manage_messages=False,
                    initial_message=message if isinstance(message, disnake.Message) else None,
                    user=message.author,
                )
            )
        )
        if isinstance(message, disnake.Message):
            await message.channel.send(
                components=components,
            )
        elif isinstance(message, disnake.ApplicationCommandInteraction):
            await message.response.send_message(
                components=components,
            )


def setup(bot: Monty) -> None:
    """Load the GithubInfo cog."""
    bot.add_cog(GithubInfo(bot))
