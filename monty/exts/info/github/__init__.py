import random
import re
from collections.abc import Mapping
from typing import Any

import attrs
import cachingutils
import disnake
import ghretos
import githubkit
from disnake.ext import commands

import monty.utils.services
from monty import constants
from monty.bot import Monty
from monty.events import MessageContext, MontyEvent
from monty.log import get_logger
from monty.utils import scheduling
from monty.utils.messages import DeleteButton, suppress_embeds

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

    async def fetch_resource(self, obj: ghretos.GitHubResource) -> githubkit.GitHubModel | None:
        """Fetch a GitHub resource."""
        # Both issues and PRs are handled by the issues endpoint, because PRs are Issues.
        if isinstance(obj, (ghretos.Issue, ghretos.PullRequest)):
            r = await self.bot.github.rest.issues.async_get(
                owner=obj.repo.owner,
                repo=obj.repo.name,
                issue_number=obj.number,
                headers={"Accept": "application/vnd.github.full+json"},
            )
            return r.parsed_data
        if isinstance(obj, (ghretos.IssueComment, ghretos.PullRequestComment)):
            r = await self.bot.github.rest.issues.async_get_comment(
                owner=obj.repo.owner,
                repo=obj.repo.name,
                comment_id=obj.comment_id,
                headers={"Accept": "application/vnd.github.full+json"},
            )
            return r.parsed_data
        if isinstance(obj, (ghretos.PullRequestReviewComment)):
            r = await self.bot.github.rest.pulls.async_get_review_comment(
                owner=obj.repo.owner,
                repo=obj.repo.name,
                comment_id=obj.comment_id,
                headers={"Accept": "application/vnd.github.full+json"},
            )
            return r.parsed_data
        if isinstance(obj, (ghretos.IssueEvent, ghretos.PullRequestEvent)):
            r = await self.bot.github.rest.issues.async_get_event(
                owner=obj.repo.owner,
                repo=obj.repo.name,
                event_id=obj.event_id,
            )
            return r.parsed_data
        if isinstance(obj, ghretos.Commit):
            r = await self.bot.github.rest.repos.async_get_commit(
                owner=obj.repo.owner,
                repo=obj.repo.name,
                ref=obj.sha,
            )
            return r.parsed_data
        if isinstance(obj, ghretos.Repo):
            r = await self.bot.github.rest.repos.async_get(
                owner=obj.owner,
                repo=obj.name,
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

    async def get_reply(
        self,
        resources: Mapping[ghretos.GitHubResource, github_handlers.InfoSize],
    ) -> dict[str, Any]:
        """Get embeds for a list of GitHub resources."""
        embeds: list[disnake.Embed] = []
        tiny_content: list[str] = []
        for match, size in resources.items():
            # premptively check supported types:
            handler = github_handlers.HANDLER_MAPPING.get(type(match))
            if handler is None:
                continue
            # TODO: handle errors on this fetch method
            resource_data = await self.fetch_resource(match)
            if resource_data is None:
                continue

            # Run resource validation
            if html_url := getattr(resource_data, "html_url", None):
                # Run the html_url through ghretos and match the resource type and ID again to ensure correctness.
                reparsed = ghretos.parse_url(html_url)
                valid: bool = True
                if reparsed is None or (
                    type(reparsed) is not type(match)
                    and hasattr(reparsed, "number")
                    and hasattr(match, "number")
                    and getattr(reparsed, "number", None) != getattr(match, "number", None)
                ):
                    valid = False
                # Specially handle pulls being issues
                if hasattr(reparsed, "number") and getattr(reparsed, "number", None) != getattr(match, "number", None):
                    valid = False
                if not valid:
                    log.warning(
                        "GitHub resource fetch returned mismatched data: expected %r, got %r",
                        match,
                        reparsed,
                    )
                    continue  # skip invalid data
            match size:
                case github_handlers.InfoSize.OGP:
                    embeds.append(handler().render(resource_data, context=match, size=size))
                case github_handlers.InfoSize.TINY:
                    tiny_content.append(handler().render(resource_data, context=match, size=size))

        resp = {}
        if tiny_content:
            content = "\n".join(tiny_content)
            resp["content"] = content
        if embeds:
            resp["embeds"] = embeds
        return resp

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
        # Use a dict to deduplicate matches, but keep the original insertion order.
        matches: dict[ghretos.GitHubResource, github_handlers.InfoSize] = {}
        # parse all of the shorthand first
        for segment in context.text.split():
            match = ghretos.parse_shorthand(segment)
            if match is not None:
                matches[match] = github_handlers.InfoSize.TINY
        for url in context.urls:
            match = ghretos.parse_url(url)
            if match is not None:
                matches[match] = github_handlers.InfoSize.OGP

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

        data = await self.get_reply(
            matches,
        )
        if not data:
            return

        if isinstance(message, disnake.Message):
            scheduling.create_task(
                suppress_embeds(
                    bot=self.bot,
                    message=message,
                )
            )

        components = []
        components.append(
            disnake.ui.ActionRow(
                DeleteButton(
                    allow_manage_messages=True,
                    user=message.author,
                )
            )
        )
        if isinstance(message, disnake.Message):
            await message.reply(
                **data,
                components=components,
                fail_if_not_exists=False,
                allowed_mentions=disnake.AllowedMentions.none(),
            )
        elif isinstance(message, disnake.ApplicationCommandInteraction):
            await message.response.send_message(
                **data,
                components=components,
                allowed_mentions=disnake.AllowedMentions.none(),
            )


def setup(bot: Monty) -> None:
    """Load the GithubInfo cog."""
    bot.add_cog(GithubInfo(bot))
