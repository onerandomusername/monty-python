import asyncio
import functools
import json
import operator
import pathlib
import random
import re
from collections.abc import Mapping
from typing import Any, TypedDict

import cachingutils
import disnake
import ghretos
import githubkit
import githubkit.exception
import githubkit.rest
from disnake.ext import commands
from typing_extensions import Protocol, Required, runtime_checkable

import monty.utils.services
from monty import constants
from monty.bot import Monty
from monty.database import GuildConfig
from monty.events import MessageContext, MontyEvent
from monty.log import get_logger
from monty.utils import responses, scheduling
from monty.utils.extensions import invoke_help_command
from monty.utils.messages import DeleteButton, suppress_embeds

from . import _handlers as github_handlers
from .client import GitHubFetcher


# Maximum number of issues in one message
MAXIMUM_ISSUES = 6


EXPANDED_ISSUE_MODAL_CUSTOM_ID = "gh:issue-expanded-modal"
EXPAND_ISSUE_CUSTOM_ID_PREFIX = "gh:issue-expand-v1:"
EXPAND_ISSUE_CUSTOM_ID_FORMAT = EXPAND_ISSUE_CUSTOM_ID_PREFIX + r"{user_id}:{state}:{org}/{repo}#{num}"
EXPAND_ISSUE_CUSTOM_ID_REGEX = re.compile(
    re.escape(EXPAND_ISSUE_CUSTOM_ID_PREFIX)
    # 1 is expanded, 0 is collapsed
    + r"(?P<user_id>[0-9]+):(?P<current_state>0|1):"
    r"(?P<org>[a-zA-Z0-9][a-zA-Z0-9\-]{1,39})\/(?P<repo>[\w\-\.]{1,100})#(?P<number>[0-9]+)"
)

repo_name_number_getter = operator.attrgetter("repo.owner", "repo.name", "number")

log = get_logger(__name__)


class GitHubShorthandAliases(TypedDict, total=False):
    owner: Required[str]
    repo: Required[str]


@runtime_checkable
class ImplementsRepository(Protocol):
    """Protocol for GitHub models that implement a repository."""

    repo: ghretos.Repo


class GithubInfo(
    commands.Cog,
    name="GitHub Information",
    slash_command_attrs={
        "contexts": disnake.InteractionContextTypes(guild=True, private_channel=True),
        "install_types": disnake.ApplicationInstallTypes(guild=True, user=True),
    },
):
    """Fetches info from GitHub."""

    def __init__(self, bot: Monty) -> None:
        self.bot = bot
        self.client: GitHubFetcher = GitHubFetcher(bot.github)
        self.short_repos: dict[str, GitHubShorthandAliases] = json.loads(
            pathlib.Path("monty/resources/repo_aliases.json").read_text()
        )

        # Validate casefold.
        assert all(
            repo == repo.casefold() and value.get("repo") and value.get("owner")
            for repo, value in self.short_repos.items()
        ), "Repository shorthand keys must be casefolded and include exactly one `/` in the data file."

        self.autolink_cache: cachingutils.MemoryCache[
            int, tuple[disnake.Message, dict[ghretos.GitHubResource, github_handlers.InfoSize]]
        ] = cachingutils.MemoryCache(timeout=600)

    async def cog_load(self) -> None:
        """Sync the ratelimit cache upon cog load."""
        await self._fetch_and_update_ratelimits()

    async def _fetch_and_update_ratelimits(self) -> None:
        async with self.bot.http_session.disabled():  # do not cache this endpoint
            r = await self.bot.github.rest.rate_limit.async_get()
        data = r.json()
        monty.utils.services.update_github_ratelimits_from_ratelimit_page(data)

    async def fetch_resource(
        self,
        resource: ghretos.GitHubResource,
    ) -> githubkit.GitHubModel:
        """Fetch a GitHub resource."""
        return await self.client.fetch_resource(resource)

    async def resolve_repo(
        self,
        repo: ghretos.Repo,
        *,
        default_user: str | None = None,
    ) -> ghretos.Repo:
        """Resolve the owner of a GitHub repository."""
        if repo.owner:
            return repo
        if repo.name in self.short_repos:
            return ghretos.Repo(
                owner=self.short_repos[repo.name]["owner"],
                name=self.short_repos[repo.name]["repo"],
            )
        r = await self.bot.github.rest.search.async_repos(q=(repo.name + " is:public"), per_page=20, order="desc")
        for repo_data in r.parsed_data.items:
            if repo_data.name.casefold() == repo.name.casefold():
                break

        else:
            # TODO: Check if the repository belongs to the default user before returning
            # Fallback to the default user if provided
            if default_user:
                return ghretos.Repo(owner=default_user, name=repo.name)
            msg = "GitHub repository not found."
            raise commands.UserInputError(msg)

        user, repo_name = repo_data.full_name.split("/", 1)

        if not isinstance(repo_data, (githubkit.rest.RepoSearchResultItem)):
            msg = "Could not resolve repository owner."
            raise ValueError(msg)
        return ghretos.Repo(owner=user, name=repo_name)

    async def get_full_reply(
        self,
        resource: ghretos.GitHubResource,
    ) -> tuple[str, list[disnake.ui.TextDisplay]] | None:
        """Get full text displays for a GitHub resource."""
        handler = github_handlers.HANDLER_MAPPING.get(type(resource))
        if handler is None:
            return None

        resource_data = await self.fetch_resource(resource)

        return handler(limit=3600).render(resource_data, context=resource, size=github_handlers.InfoSize.FULL)

    async def get_reply(
        self,
        resources: Mapping[ghretos.GitHubResource, github_handlers.InfoSize],
        *,
        limit: int | None = None,
        settings: ghretos.MatcherSettings | None = None,
    ) -> dict[str, Any]:
        """Get embeds for a list of GitHub resources."""
        embeds: list[disnake.Embed] = []
        tiny_content: list[str] = []

        coros = []
        for match in resources:
            # premptively check supported types:
            handler = github_handlers.HANDLER_MAPPING.get(type(match))
            if handler is None:
                # append a useless coro to keep the order correct
                coros.append(asyncio.sleep(0))
                continue
            coros.append(self.fetch_resource(match))

        # TODO: handle errors on this fetch method
        fut = await asyncio.gather(*coros, return_exceptions=True)

        tiny_callables = []

        repo: str | bool | None = None
        owner: str | None | bool = None
        actual_parsed_resources = set[ghretos.GitHubResource]()
        for resource_data, (match, size) in zip(fut, resources.items(), strict=True):
            if isinstance(resource_data, BaseException):
                if (
                    isinstance(resource_data, githubkit.exception.RequestFailed)
                    and resource_data.response.status_code == 404
                ):
                    log.info("GitHub resource %r not found (404).", match)
                    continue
                log.warning(
                    "GitHub resource fetch for %r resulted in an exception: %r",
                    match,
                    resource_data,
                )
                continue
            # Reassert we have a handler
            handler = github_handlers.HANDLER_MAPPING.get(type(match))
            if not handler:
                continue

            if isinstance(match, ImplementsRepository):
                if repo is None:
                    repo = match.repo.name.casefold()
                if repo != match.repo.name.casefold():
                    repo = True  # multiple repos
                if owner is not True:
                    if owner is None:
                        owner = match.repo.owner.casefold()
                    if owner != match.repo.owner.casefold():
                        owner = True  # multiple owners

            # Run resource validation
            if html_url := getattr(resource_data, "html_url", None):
                # Run the html_url through ghretos and match the resource type and ID again to ensure correctness.
                if settings:
                    reparsed = ghretos.parse_url(html_url, settings=settings)
                else:
                    reparsed = ghretos.parse_url(html_url)

                if reparsed is None or not isinstance(
                    reparsed, github_handlers.GITHUB_LINK_TRAVERSAL_EQUALS.get(type(match), type(match))
                ):
                    log.warning(
                        "GitHub resource fetch returned mismatched data: expected %r, got %r",
                        match,
                        reparsed,
                    )
                    continue  # skip invalid data

                if match != reparsed and isinstance(reparsed, ImplementsRepository):
                    if repo is None:
                        repo = reparsed.repo.name.casefold()
                    if repo != reparsed.repo.name.casefold():
                        repo = True  # multiple repos
                    if owner is not True:
                        if owner is None:
                            owner = reparsed.repo.owner.casefold()
                        if owner != reparsed.repo.owner.casefold():
                            owner = True  # multiple owners

                match = reparsed  # use the reparsed version for more accurate data

            if match in actual_parsed_resources:
                continue
            actual_parsed_resources.add(match)

            match size:
                case github_handlers.InfoSize.OGP:
                    embeds.append(handler(limit=limit).render(resource_data, context=match, size=size))
                case github_handlers.InfoSize.TINY:
                    method = functools.partial(handler(limit=limit).render_tiny, resource_data, context=match)
                    tiny_callables.append(method)

        if tiny_callables:
            if owner is True:
                repo = True
            else:
                owner = False
            if repo is not True:
                repo = False
            tiny_content.extend(
                tiny_callable(
                    include_repo=repo,
                    include_owner=owner,
                )
                for tiny_callable in tiny_callables
            )

        resp = {}
        if tiny_content:
            title = ""
            if embeds:
                title += "GitHub quick links"
            tiny_embed = disnake.Embed(
                description="\n".join(tiny_content),
                colour=constants.GHColour.success,
            )
            if title:
                tiny_embed.set_author(name=title)
            embeds.insert(0, tiny_embed)

        if embeds:
            resp["embeds"] = embeds
        return resp

    def _get_base_matcher_settings(self) -> ghretos.MatcherSettings:
        matcher_settings = ghretos.MatcherSettings.none()
        matcher_settings.require_strict_type = False
        return matcher_settings

    def get_command_matcher_settings(self) -> ghretos.MatcherSettings:
        """Get matcher settings for command usage.

        These are every type which has handlers.
        """
        matcher_settings = self._get_base_matcher_settings()
        matcher_settings.shorthand = True
        matcher_settings.short_numberables = True
        matcher_settings.short_repo = True
        matcher_settings.short_bare_username = True

        matcher_settings.issues = True
        matcher_settings.pull_requests = True
        matcher_settings.issue_comments = True
        matcher_settings.pull_request_comments = True
        matcher_settings.pull_request_review_comments = True
        matcher_settings.pull_request_reviews = True
        matcher_settings.discussions = True
        matcher_settings.discussion_comments = True
        return matcher_settings

    async def get_auto_responder_matcher_settings(self, guild_id: int, config: GuildConfig) -> ghretos.MatcherSettings:
        """Get matcher settings based on guild configuration."""
        matcher_settings = self._get_base_matcher_settings()
        discussions_allowed: bool = False
        if config.github_issue_linking:
            matcher_settings.shorthand = True
            matcher_settings.short_numberables = True
            if await self.bot.guild_has_feature(guild_id, constants.Feature.GITHUB_ISSUE_LINKS):
                matcher_settings.issues = True
                matcher_settings.pull_requests = True
            if discussions_allowed := await self.bot.guild_has_feature(guild_id, constants.Feature.GITHUB_DISCUSSIONS):
                matcher_settings.discussions = True

        if config.github_comment_linking and await self.bot.guild_has_feature(
            guild_id, constants.Feature.GITHUB_COMMENT_LINKS
        ):
            matcher_settings.issue_comments = True
            matcher_settings.pull_request_comments = True
            matcher_settings.pull_request_review_comments = True
            matcher_settings.pull_request_reviews = True
            if discussions_allowed or (
                discussions_allowed := await self.bot.guild_has_feature(guild_id, constants.Feature.GITHUB_DISCUSSIONS)
            ):
                matcher_settings.discussion_comments = True

        return matcher_settings

    async def parse_contents(
        self, context: MessageContext, *, settings: ghretos.MatcherSettings, default_user: str | None = None
    ) -> dict[ghretos.GitHubResource, github_handlers.InfoSize]:
        """Parse message contents for GitHub resources."""
        # Use a dict to deduplicate matches, but keep the original insertion order.
        matches: dict[ghretos.GitHubResource, github_handlers.InfoSize] = {}
        # parse all of the shorthand first
        for segment in context.text.split():
            match = ghretos.parse_shorthand(
                segment,
                allow_optional_user=True,
                settings=settings,
            )
            if match is None:
                continue
            # resolve the repo owner if needed
            try:
                if isinstance(match, ghretos.Repo) and not match.owner:
                    match = await self.resolve_repo(match, default_user=default_user)
                elif isinstance(match, ImplementsRepository) and not match.repo.owner:
                    object.__setattr__(match, "repo", await self.resolve_repo(match.repo, default_user=default_user))
            except commands.UserInputError:
                continue

            matches[match] = github_handlers.InfoSize.TINY

        for url in context.urls:
            match = ghretos.parse_url(
                url,
                settings=settings,
            )
            if match is not None:
                matches[match] = github_handlers.InfoSize.OGP

        if not matches:
            return {}

        def sort_key(item: ghretos.GitHubResource) -> tuple:
            try:
                result = repo_name_number_getter(item)
            except AttributeError:
                return ("", "", 0)
            owner, repo, number = result
            return owner.casefold(), repo.casefold(), number

        return dict(sorted(matches.items(), key=lambda item: sort_key(item[0])))

    @commands.group(
        name="github", description="Fetch GitHub information.", aliases=("gh",), invoke_without_command=True
    )
    async def github_group(self, ctx: commands.Context, *args) -> None:
        """Group for GitHub related commands."""
        if not args:
            await invoke_help_command(ctx)
            return

        # Shortcut user:
        # Intentionally match 2 on the args here
        # Allow messages such as !github username extra words
        # but also support !github username repo
        if len(args) != 2 and re.fullmatch(r"^[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,38})$", args[0]):
            await self.github_user(ctx, args[0])
            return
        settings = ghretos.MatcherSettings.none()
        # enable what we have handlers for
        settings.shorthand = True
        settings.short_repo = True
        resource = ghretos.parse_shorthand(" ".join(args), settings=settings)

        if isinstance(resource, ghretos.User):
            await self.github_user(ctx, resource.login)
            return
        if isinstance(resource, ghretos.Repo):
            await self.github_repo(ctx, resource.full_name)
            return
        if isinstance(resource, tuple(github_handlers.HANDLER_MAPPING.keys())):
            data = await self.get_reply({resource: github_handlers.InfoSize.OGP}, limit=850, settings=settings)
            if data:
                components: list[disnake.ui.Container | disnake.ui.ActionRow] = []
                components.append(
                    disnake.ui.ActionRow(
                        DeleteButton(
                            allow_manage_messages=True,
                            user=ctx.author,
                            initial_message=ctx.message,
                        )
                    )
                )
                await ctx.reply(
                    components=components,
                    fail_if_not_exists=False,
                    allowed_mentions=disnake.AllowedMentions.none(),
                    **data,
                )
                return

        msg = "Could not parse a valid GitHub resource from input."
        raise commands.BadArgument(msg)

    @github_group.command(name="user", description="Fetch GitHub user information.")
    async def github_user(self, ctx: commands.Context, user: str) -> None:
        """Fetch GitHub user information."""
        # validate the user
        if not re.fullmatch(r"^[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,38})$", user):
            msg = (
                "Invalid GitHub username. Usernames must be 1-39 characters long, "
                "and can only contain alphanumeric characters or hyphens."
            )
            raise commands.BadArgument(msg)
        context = ghretos.User(login=user)
        try:
            obj = await self.client.fetch_user(username=user)
        except githubkit.exception.RequestFailed as e:
            if e.response.status_code == 404:
                msg = "GitHub user not found."
                raise commands.UserInputError(msg) from e
            raise
        components: list[disnake.ui.Container | disnake.ui.ActionRow] = []
        embed = github_handlers.UserRenderer().render_ogp(obj, context=context)
        components.append(
            disnake.ui.ActionRow(DeleteButton(allow_manage_messages=True, user=ctx.author, initial_message=ctx.message))
        )
        await ctx.send(embed=embed, components=components)

    @github_group.command(name="repo", aliases=("repository", "repo_info"))
    async def github_repo(self, ctx: commands.Context, user_and_repo: str, repo: str = "") -> None:
        """Fetch GitHub repository information."""
        # validate the repo
        await ctx.trigger_typing()
        obj: githubkit.rest.FullRepository | githubkit.rest.RepoSearchResultItem | None = None
        if user_and_repo.count("/") == 1 and not repo:
            user, repo = user_and_repo.split("/", 1)
        elif user_and_repo.count("/") > 1:
            msg = "Invalid repository format. Please use `user/repo`."
            raise commands.BadArgument(msg)
        else:
            repo = user_and_repo
            # Resolve the user from the repo name when possible
            repo_shorthand = await self.resolve_repo(ghretos.Repo(owner="", name=repo))
            user = repo_shorthand.owner
            repo = repo_shorthand.name

        if not repo:
            msg = "Repository name is required."
            raise commands.BadArgument(msg)
        if not re.fullmatch(r"^[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,38})$", user):
            msg = "Invalid GitHub username."
            raise commands.BadArgument(msg)
        if not re.fullmatch(r"^[\w\-\.]{1,100}$", repo):
            msg = "Invalid GitHub repository name."
            raise commands.BadArgument(msg)

        context = ghretos.Repo(owner=user, name=repo)
        try:
            obj = await self.client.fetch_repo(owner=user, repo=repo)
        except githubkit.exception.RequestFailed as e:
            if e.response.status_code == 404:
                msg = "GitHub repository not found."
                raise commands.BadArgument(msg) from e
            raise

        components: list[disnake.ui.Container | disnake.ui.ActionRow] = []
        embed = github_handlers.RepoRenderer().render_ogp(obj, context=context)
        components.append(
            disnake.ui.ActionRow(DeleteButton(allow_manage_messages=True, user=ctx.author, initial_message=ctx.message))
        )
        await ctx.send(embed=embed, components=components)

    @github_group.command(name="ratelimit", aliases=("rl",), hidden=True)
    @commands.is_owner()
    async def ratelimits_command(self, ctx: commands.Context, refresh: bool = False) -> None:
        """Check the current RateLimits connected to GitHub."""
        embed = disnake.Embed(title="GitHub Ratelimits")
        if refresh:
            await self._fetch_and_update_ratelimits()

        use_inline = len(monty.utils.services.GITHUB_RATELIMITS) <= 18  # 25 fields, 3 per line, 1 for the seperator.
        for i, (resource_name, rate_limit) in enumerate(monty.utils.services.GITHUB_RATELIMITS.items()):
            embed_value = ""
            embed_value += f"**`limit`**: `{rate_limit.limit}`\n"
            embed_value += f"**`remaining`**: `{rate_limit.remaining}`\n"
            embed_value += f"**`reset`**: <t:{rate_limit.reset}:R>\n"
            embed_value += f"**`used`**: `{rate_limit.used}`\n"
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

    @commands.slash_command(name="github", description="Fetch GitHub information.")
    async def slash_github_group(self, inter: disnake.ApplicationCommandInteraction) -> None:
        """Group for GitHub related commands."""

    @slash_github_group.sub_command(name="info", description="Fetch GitHub information.")
    async def slash_github_info(self, inter: disnake.ApplicationCommandInteraction, arg: str) -> None:
        """Fetch GitHub information.

        Parameters
        ----------
        arg: str
            The GitHub resource to view . Can be a URL or shorthand like owner/repo#issue_number.
        """
        context = MessageContext(arg)
        matches: dict[ghretos.GitHubResource, github_handlers.InfoSize] = {}

        settings = self.get_command_matcher_settings()
        for segment in context.text.split():
            match = ghretos.parse_shorthand(segment, settings=settings, allow_optional_user=True)
            if match is not None:
                if isinstance(match, ghretos.Repo) and not match.owner:
                    match = await self.resolve_repo(match)
                elif isinstance(match, ImplementsRepository) and not match.repo.owner:
                    object.__setattr__(match, "repo", await self.resolve_repo(match.repo))
                matches[match] = github_handlers.InfoSize.OGP
        for url in context.urls:
            match = ghretos.parse_url(url, settings=settings)
            if match is not None:
                matches[match] = github_handlers.InfoSize.OGP

        if not matches:
            msg = "Could not parse any GitHub resources from input. Provide either a GitHub URL or supported shorthand."
            raise commands.BadArgument(msg)

        def sort_key(item: ghretos.GitHubResource) -> tuple:
            try:
                return tuple(operator.attrgetter("repo.owner", "repo.name", "number")(item))
            except AttributeError:
                return ("", "", 0)

        matches = dict(sorted(matches.items(), key=lambda item: sort_key(item[0])))

        data = await self.get_reply(matches, limit=650, settings=settings)

        if not data:
            msg = (
                "Could not fetch information for the provided GitHub resources. "
                "Please check your input and be sure they exist."
            )
            raise commands.BadArgument(msg)

        components: list[disnake.ui.ActionRow] = []
        components.append(
            disnake.ui.ActionRow(
                DeleteButton(
                    allow_manage_messages=True,
                    user=inter.author,
                )
            )
        )
        # add in a button to expand/collapse if there is exactly one issue/pr/discussion
        # and it is not a comment.
        if len(matches) == 1:
            match = next(iter(matches.keys()))
            if (
                isinstance(
                    match,
                    (
                        ghretos.Issue,
                        ghretos.PullRequest,
                        ghretos.Discussion,
                        ghretos.NumberedResource,
                    ),
                )
                and (embeds := data.get("embeds"))
                and embeds[0].description.endswith("...")
            ):
                current_state = 0  # collapsed
                expand_custom_id = EXPAND_ISSUE_CUSTOM_ID_FORMAT.format(
                    user_id=inter.author.id,
                    state=current_state,
                    org=match.repo.owner,
                    repo=match.repo.name,
                    num=match.number,
                )
                expand_button = disnake.ui.Button(
                    label="Show More",
                    style=disnake.ButtonStyle.primary,
                    custom_id=expand_custom_id,
                )
                components[-1].append_item(expand_button)
        await inter.response.send_message(
            **data,
            components=components,
            allowed_mentions=disnake.AllowedMentions.none(),
        )

    @commands.Cog.listener("on_" + MontyEvent.monty_message_processed.value)
    async def on_message_automatic_issue_link(
        self,
        message: disnake.Message,
        context: MessageContext,
    ) -> None:
        """
        Automatic issue linking.

        Listener to retrieve issue(s) from a GitHub repository using automatic linking if matching <org>/<repo>#<issue>.
        """
        if not message.guild:
            return
        command_context = await self.bot.get_context(message)
        if command_context.command and command_context.command.cog is self:
            return  # do not auto-link in own commands

        app_permissions = message.channel.permissions_for(message.guild.me)
        if not app_permissions.send_messages:
            return  # bot cannot send messages in this channel

        # in order to support shorthand, we need to check guild configuration
        guild_config = await self.bot.ensure_guild_config(message.guild.id)

        matcher_settings = await self.get_auto_responder_matcher_settings(message.guild.id, guild_config)

        matches = await self.parse_contents(
            context,
            settings=matcher_settings,
            default_user=guild_config.github_issues_org,
        )

        if len(matches) > MAXIMUM_ISSUES:
            embed = disnake.Embed(
                title=random.choice(responses.USER_INPUT_ERROR_REPLIES),
                color=responses.DEFAULT_FAILURE_COLOUR,
                description=f"Too many issues/PRs! (maximum of {MAXIMUM_ISSUES})",
            )
            sent_message = await message.channel.send(embed=embed)
            self.autolink_cache.set(
                message.id,
                (sent_message, matches),
            )
            return

        data = await self.get_reply(
            matches,
            settings=matcher_settings,
        )
        if not data:
            return

        if app_permissions.manage_messages and not message.flags.suppress_embeds:
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
        sent_message = await message.reply(
            **data,
            components=components,
            fail_if_not_exists=False,
            allowed_mentions=disnake.AllowedMentions.none(),
        )

        self.autolink_cache.set(
            message.id,
            (sent_message, matches),
        )

    @commands.Cog.listener("on_message_edit")
    async def on_message_edit_automatic_issue_link(self, before: disnake.Message, after: disnake.Message) -> None:
        """Automatic issue linking on message edit."""
        if not after.guild:
            return
        if before.content == after.content:
            return  # no content change

        cached = self.autolink_cache.get(after.id)
        if cached is None:
            return

        app_permissions = after.channel.permissions_for(after.guild.me)

        sent_message, previous_matches = cached

        context = MessageContext(after.content)

        guild_config = await self.bot.ensure_guild_config(after.guild.id)
        matcher_settings = await self.get_auto_responder_matcher_settings(after.guild.id, guild_config)
        matches = await self.parse_contents(
            context,
            settings=matcher_settings,
            default_user=guild_config.github_issues_org,
        )

        if matches == dict(previous_matches):
            return  # no new matches

        if len(matches) > MAXIMUM_ISSUES:
            embed = disnake.Embed(
                title=random.choice(responses.USER_INPUT_ERROR_REPLIES),
                color=responses.DEFAULT_FAILURE_COLOUR,
                description=f"Too many issues/PRs! (maximum of {MAXIMUM_ISSUES})",
            )
            sent_message = await sent_message.edit(embed=embed)
            self.autolink_cache.set(
                after.id,
                (sent_message, matches),
            )
            return

        data = await self.get_reply(
            matches,
            settings=matcher_settings,
        )
        if not data:
            return

        if app_permissions.manage_messages and not before.flags.suppress_embeds:
            scheduling.create_task(
                suppress_embeds(
                    bot=self.bot,
                    message=after,
                )
            )

        components = []
        if "components" in data:
            components.extend(data["components"])
            data.pop("components")

        components.append(
            disnake.ui.ActionRow(
                DeleteButton(
                    allow_manage_messages=True,
                    user=after.author,
                )
            )
        )
        sent_message = await sent_message.edit(
            **data,
            components=components,
            allowed_mentions=disnake.AllowedMentions.none(),
        )

        # update the cache with the new matches
        self.autolink_cache.set(
            after.id,
            (sent_message, matches),
        )

    @commands.Cog.listener("on_button_click")
    async def show_expanded_information(
        self,
        interaction: disnake.MessageInteraction,
    ) -> None:
        """Show expanded information for a GitHub issue."""
        match = EXPAND_ISSUE_CUSTOM_ID_REGEX.match(interaction.data.custom_id)
        if not match:
            return

        settings = self.get_command_matcher_settings()

        gh_resource = ghretos.parse_shorthand(
            f"{match.group('org')}/{match.group('repo')}#{match.group('number')}", settings=settings
        )
        if gh_resource is None:
            await interaction.response.send_message(
                "Could not parse the GitHub resource to expand.",
                ephemeral=True,
            )
            return

        resp = await self.get_full_reply(gh_resource)
        if not resp or not resp[1]:
            await interaction.response.send_message(
                "Could not fetch the GitHub resource to expand or collapse.",
                ephemeral=True,
            )
            return

        _title, data = resp

        title = getattr(getattr(gh_resource, "repo", None), "full_name", None) or ""
        if title:
            title += f"#{getattr(gh_resource, 'number', '')}"
        if len(title) > 45:
            title = title.split("/", 1)[1]
        if len(title) > 45:
            title = title[:42] + "..."
        await interaction.response.send_modal(
            title=title,
            custom_id=EXPANDED_ISSUE_MODAL_CUSTOM_ID,
            components=data,
        )

    @commands.Cog.listener("on_modal_submit")
    async def handle_modal_submit(self, interaction: disnake.ModalInteraction) -> None:
        """Handle the submission of the expanded issue modal."""
        if interaction.custom_id != EXPANDED_ISSUE_MODAL_CUSTOM_ID:
            return
        await interaction.response.defer(with_message=False)
