import asyncio
import base64
import functools
import operator
import random
import re
from collections.abc import Mapping
from typing import Any, overload

import attrs
import cachingutils
import disnake
import ghretos
import githubkit
import githubkit.exception
import githubkit.rest
import msgpack
from disnake.ext import commands

import monty.utils.services
from monty import constants
from monty.bot import Monty
from monty.database import GuildConfig
from monty.events import MessageContext, MontyEvent
from monty.log import get_logger
from monty.utils import scheduling
from monty.utils.messages import DeleteButton, suppress_embeds

from . import _handlers as github_handlers
from . import graphql_models


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
                    type
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
        "contexts": disnake.InteractionContextTypes(guild=True, private_channel=True),
        "install_types": disnake.ApplicationInstallTypes(guild=True, user=True),
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

    def _format_github_global_id(self, prefix: str, *ids: int, template: int = 0) -> str:
        # This is not documented, but is at least the current format as of writing this comment.
        # These IDs are supposed to be treated as opaque strings, but fetching specific resources like
        # issue/discussion comments via graphql is a huge pain otherwise when only knowing the integer ID
        packed = msgpack.packb(
            [
                # template index; global IDs of a specific type *can* have multiple different templates
                # (i.e. sets of variables that follow); in almost all cases, this is 0
                template,
                # resource IDs, variable amount depending on global ID type
                *ids,
            ]
        )
        encoded = base64.urlsafe_b64encode(packed).decode()
        encoded = encoded.rstrip("=")  # this isn't necessary, but github generates these IDs without padding
        return f"{prefix}_{encoded}"

    @overload
    async def fetch_resource(self, obj: ghretos.User) -> githubkit.rest.PublicUser: ...

    @overload
    async def fetch_resource(self, obj: ghretos.Repo) -> githubkit.rest.Repository: ...

    @overload
    async def fetch_resource(self, obj: ghretos.Issue) -> githubkit.rest.Issue | githubkit.rest.Discussion: ...
    @overload
    async def fetch_resource(self, obj: ghretos.PullRequest) -> githubkit.rest.Issue | githubkit.rest.Discussion: ...
    @overload
    async def fetch_resource(self, obj: ghretos.IssueComment) -> githubkit.rest.IssueComment: ...
    @overload
    async def fetch_resource(self, obj: ghretos.PullRequestComment) -> githubkit.rest.IssueComment: ...
    @overload
    async def fetch_resource(
        self, obj: ghretos.PullRequestReviewComment
    ) -> githubkit.rest.PullRequestReviewComment: ...
    @overload
    async def fetch_resource(self, obj: ghretos.Discussion) -> githubkit.rest.Issue | githubkit.rest.Discussion: ...
    @overload
    async def fetch_resource(self, obj: ghretos.DiscussionComment) -> graphql_models.DiscussionComment: ...
    @overload
    async def fetch_resource(self, obj: ghretos.IssueEvent) -> githubkit.rest.IssueEvent: ...
    @overload
    async def fetch_resource(self, obj: ghretos.PullRequestEvent) -> githubkit.rest.IssueEvent: ...
    @overload
    async def fetch_resource(self, obj: ghretos.Commit) -> githubkit.rest.Commit: ...
    @overload
    async def fetch_resource(self, obj: ghretos.Repo) -> githubkit.rest.Repository: ...
    @overload
    async def fetch_resource(self, obj: ghretos.GitHubResource) -> githubkit.GitHubModel: ...

    async def fetch_resource(self, obj: ghretos.GitHubResource) -> githubkit.GitHubModel:
        """Fetch a GitHub resource."""
        # TODO: add repo exists validation before fetching multiple resources from one repo?
        # This would reduce wasted requests on private repos, and keep discussions from making many extra requests.
        try_discussion: bool = False

        headers = {
            "Accept": "application/vnd.github.full+json",
            "Cache-Control": "max-age=14400",
        }

        # Both issues and PRs are handled by the issues endpoint, because PRs are Issues.
        if isinstance(obj, (ghretos.Issue, ghretos.PullRequest, ghretos.NumberedResource)):
            try:
                r = await self.bot.github.rest.issues.async_get(
                    owner=obj.repo.owner,
                    repo=obj.repo.name,
                    issue_number=obj.number,
                    headers=headers,
                )
            except githubkit.exception.RequestFailed as e:
                if e.response.status_code != 404:
                    raise
                try_discussion = True
            else:
                return r.parsed_data
        if isinstance(obj, (ghretos.IssueComment, ghretos.PullRequestComment)):
            r = await self.bot.github.rest.issues.async_get_comment(
                owner=obj.repo.owner,
                repo=obj.repo.name,
                comment_id=obj.comment_id,
                headers=headers,
            )
            return r.parsed_data
        if isinstance(obj, (ghretos.PullRequestReviewComment)):
            r = await self.bot.github.rest.pulls.async_get_review_comment(
                owner=obj.repo.owner,
                repo=obj.repo.name,
                comment_id=obj.comment_id,
                headers=headers,
            )
            return r.parsed_data
        if (
            try_discussion and isinstance(obj, (ghretos.Issue, ghretos.PullRequest, ghretos.NumberedResource))
        ) or isinstance(obj, ghretos.Discussion):
            url = f"/repos/{obj.repo.owner}/{obj.repo.name}/discussions/{obj.number}"
            try:
                r = await self.bot.github.arequest(
                    "GET",
                    url,
                    headers=headers | {"X-GitHub-Api-Version": self.bot.github.rest.meta._REST_API_VERSION},
                    response_model=githubkit.rest.Discussion,
                )
            except githubkit.exception.RequestFailed as e:
                if try_discussion or e.response.status_code != 404:
                    raise
                r = await self.bot.github.rest.issues.async_get(
                    owner=obj.repo.owner,
                    repo=obj.repo.name,
                    issue_number=obj.number,
                    headers=headers,
                )
            return r.parsed_data
        if isinstance(obj, (ghretos.IssueEvent, ghretos.PullRequestEvent)):
            r = await self.bot.github.rest.issues.async_get_event(
                owner=obj.repo.owner,
                repo=obj.repo.name,
                event_id=obj.event_id,
                headers=headers,
            )
            return r.parsed_data
        if isinstance(obj, ghretos.DiscussionComment):
            r = await self.bot.github.graphql.arequest(
                DISCUSSION_COMMENT_GRAPHQL_QUERY,
                variables={"id": self._format_github_global_id("DC", 0, obj.comment_id)},
            )
            return graphql_models.DiscussionComment(**r["node"])

        if isinstance(obj, ghretos.Commit):
            r = await self.bot.github.rest.repos.async_get_commit(
                owner=obj.repo.owner,
                repo=obj.repo.name,
                ref=obj.sha,
                headers=headers,
            )
            return r.parsed_data
        if isinstance(obj, ghretos.Repo):
            r = await self.bot.github.rest.repos.async_get(
                owner=obj.owner,
                repo=obj.name,
                headers=headers,
            )
            return r.parsed_data

        if isinstance(obj, ghretos.User):
            r = await self.bot.github.rest.users.async_get_by_username(
                username=obj.login,
                headers=headers,
            )
            data = r.parsed_data
            # Even though we use a token with no additional scopes, validate that we CERTAINLY only have public data.
            if data.user_view_type != "public":
                msg = "User is not public"
                raise ValueError(msg)
            return data

        raise NotImplementedError  # Type is not yet supported

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

            if match_repo := getattr(match, "repo", None):
                if repo is None:
                    repo = match_repo.name
                if repo != match_repo.name:
                    repo = True  # multiple repos
                if owner is not True:
                    if owner is None:
                        owner = match_repo.owner
                    if owner != match_repo.owner:
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

                if match_repo := getattr(reparsed, "repo", None):
                    if repo is None:
                        repo = match_repo.name
                    if repo != match_repo.name:
                        repo = True  # multiple repos
                    if owner is not True:
                        if owner is None:
                            owner = match_repo.owner
                        if owner != match_repo.owner:
                            owner = True  # multiple owners

                match = reparsed  # use the reparsed version for more accurate data

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

    @commands.group(
        name="github", description="Fetch GitHub information.", aliases=("gh",), invoke_without_command=True
    )
    async def github_group(self, ctx: commands.Context, *args) -> None:
        """Group for GitHub related commands."""
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
            data = await self.get_reply({resource: github_handlers.InfoSize.OGP}, limit=850)
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

        await ctx.send(
            f"{constants.Emojis.decline} Could not parse GitHub resource from input.",
            components=DeleteButton(
                allow_manage_messages=True,
                user=ctx.author,
                initial_message=ctx.message,
            ),
        )
        return

    @github_group.command(name="user", description="Fetch GitHub user information.")
    async def github_user(self, ctx: commands.Context, user: str) -> None:
        """Fetch GitHub user information."""
        # validate the user
        if not re.fullmatch(r"^[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,38})$", user):
            await ctx.send(
                f"{constants.Emojis.decline} Invalid GitHub username.",
                components=[
                    DeleteButton(
                        allow_manage_messages=True,
                        user=ctx.author,
                        initial_message=ctx.message,
                    )
                ],
            )
            return
        context = ghretos.User(login=user)
        try:
            obj = await self.fetch_resource(context)
        except githubkit.exception.RequestFailed as e:
            if e.response.status_code == 404:
                msg = "GitHub user not found."
                raise commands.UserInputError(msg) from e
            raise
        components: list[disnake.ui.Container | disnake.ui.ActionRow] = []
        components.append(github_handlers.UserRenderer().render_ogp_cv2(obj, context=context))
        components.append(
            disnake.ui.ActionRow(DeleteButton(allow_manage_messages=True, user=ctx.author, initial_message=ctx.message))
        )
        await ctx.send(components=components)

    @github_group.command(name="repo", description="Fetch GitHub repository information.")
    async def github_repo(self, ctx: commands.Context, user_and_repo: str, repo: str = "") -> None:
        """Fetch GitHub repository information."""
        # validate the repo
        if user_and_repo.count("/") == 1 and not repo:
            user, repo = user_and_repo.split("/", 1)
        else:
            user = user_and_repo
        if not repo:
            msg = "Repository name is required."
            raise commands.UserInputError(msg)
        if not re.fullmatch(r"^[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,38})$", user):
            msg = "Invalid GitHub username."
            raise commands.UserInputError(msg)
        if not re.fullmatch(r"^[\w\-\.]{1,100}$", repo):
            msg = "Invalid GitHub repository name."
            raise commands.UserInputError(msg)

        context = ghretos.Repo(owner=user, name=repo)
        try:
            obj = await self.fetch_resource(context)
        except githubkit.exception.RequestFailed as e:
            if e.response.status_code == 404:
                msg = "GitHub repository not found."
                raise commands.UserInputError(msg) from e
            raise
        components: list[disnake.ui.Container | disnake.ui.ActionRow] = []
        components.append(github_handlers.RepoRenderer().render_ogp_cv2(obj, context=context))
        components.append(
            disnake.ui.ActionRow(DeleteButton(allow_manage_messages=True, user=ctx.author, initial_message=ctx.message))
        )
        await ctx.send(components=components)

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

    @commands.slash_command(name="github", description="Fetch GitHub information.")
    async def slash_github_group(self, inter: disnake.ApplicationCommandInteraction) -> None:
        """Group for GitHub related commands."""

    @slash_github_group.sub_command(name="info", description="Fetch GitHub information.")
    async def slash_github_info(self, inter: disnake.ApplicationCommandInteraction, arg: str) -> None:
        """Fetch GitHub information.

        Parameters
        ----------
        arg: str
            The GitHub resource(s) to fetch information about. Can be a URL or shorthand like
        """
        context = MessageContext(arg)
        matches: dict[ghretos.GitHubResource, github_handlers.InfoSize] = {}

        settings = self.get_command_matcher_settings()
        for segment in context.text.split():
            match = ghretos.parse_shorthand(segment, settings=settings)
            if match is not None:
                matches[match] = github_handlers.InfoSize.OGP
        for url in context.urls:
            match = ghretos.parse_url(url, settings=settings)
            if match is not None:
                matches[match] = github_handlers.InfoSize.OGP

        if not matches:
            await inter.response.send_message(
                f"{constants.Emojis.decline} No GitHub resources found in input.",
                ephemeral=True,
            )
            return

        def sort_key(item: ghretos.GitHubResource) -> tuple:
            try:
                return tuple(operator.attrgetter("repo.owner", "repo.name", "number")(item))
            except AttributeError:
                return ("", "", 0)

        matches = dict(sorted(matches.items(), key=lambda item: sort_key(item[0])))

        data = await self.get_reply(matches, limit=650, settings=settings)

        if not data:
            await inter.response.send_message(
                f"{constants.Emojis.decline} Could not fetch any GitHub resources from input.",
                ephemeral=True,
            )
            return

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

        # in order to support shorthand, we need to check guild configuration
        guild_config = await self.bot.ensure_guild_config(message.guild.id)

        matcher_settings = await self.get_auto_responder_matcher_settings(message.guild.id, guild_config)

        # Use a dict to deduplicate matches, but keep the original insertion order.
        matches: dict[ghretos.GitHubResource, github_handlers.InfoSize] = {}
        # parse all of the shorthand first
        for segment in context.text.split():
            match = ghretos.parse_shorthand(
                segment,
                default_user=guild_config.github_issues_org,
                settings=matcher_settings,
            )
            if match is not None:
                matches[match] = github_handlers.InfoSize.TINY
        for url in context.urls:
            match = ghretos.parse_url(
                url,
                settings=matcher_settings,
            )
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

        def sort_key(item: ghretos.GitHubResource) -> tuple:
            try:
                return tuple(operator.attrgetter("repo.owner", "repo.name", "number")(item))
            except AttributeError:
                return ("", "", 0)

        matches = dict(sorted(matches.items(), key=lambda item: sort_key(item[0])))

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


def setup(bot: Monty) -> None:
    """Load the GithubInfo cog."""
    bot.add_cog(GithubInfo(bot))
