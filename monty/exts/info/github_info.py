import asyncio
import contextlib
import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, AsyncGenerator, Callable, Dict, List, NamedTuple, Optional, Tuple, TypeVar, Union, overload
from urllib.parse import quote, quote_plus
from weakref import WeakValueDictionary

import cachingutils
import cachingutils.redis
import disnake
import gql
import gql.client
from disnake.ext import commands
from gql.transport.aiohttp import AIOHTTPTransport
from gql.transport.exceptions import TransportError, TransportQueryError

from monty import constants
from monty.bot import Monty
from monty.database import GuildConfig
from monty.exts.info.codesnippets import GITHUB_HEADERS
from monty.log import get_logger
from monty.utils.extensions import invoke_help_command
from monty.utils.helpers import redis_cache
from monty.utils.messages import DeleteButton


KT = TypeVar("KT")
VT = TypeVar("VT")

BAD_RESPONSE = {
    403: "Rate limit has been hit! Please try again later!",
    404: "Issue/pull request not located! Please enter a valid number!",
}


GITHUB_API_URL = "https://api.github.com"

ORG_REPOS_ENDPOINT = f"{GITHUB_API_URL}/orgs/{{org}}/repos?per_page=100&type=public"
USER_REPOS_ENDPOINT = f"{GITHUB_API_URL}/users/{{user}}/repos?per_page=100&type=public"
ISSUE_ENDPOINT = f"{GITHUB_API_URL}/repos/{{user}}/{{repository}}/issues/{{number}}"
PR_ENDPOINT = f"{GITHUB_API_URL}/repos/{{user}}/{{repository}}/pulls/{{number}}"
LIST_PULLS_ENDPOINT = f"{GITHUB_API_URL}/repos/{{user}}/{{repository}}/pulls?per_page=100"
LIST_ISSUES_ENDPOINT = f"{GITHUB_API_URL}/repos/{{user}}/{{repository}}/issues?per_page=100"

REQUEST_HEADERS = {
    "Accept": "application/vnd.github.v3+json",
}

if GITHUB_TOKEN := constants.Tokens.github:
    REQUEST_HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"

# Maximum number of issues in one message
MAXIMUM_ISSUES = 6

# webhooks owned by this application that aren't the following
# id (as that would be an interaction response) will relay autolinkers
CROSSCHAT_BOT = 931285254319247400

# Regex used when looking for automatic linking in messages
# regex101 of current regex https://regex101.com/r/V2ji8M/6
AUTOMATIC_REGEX = re.compile(
    r"((?P<org>[a-zA-Z0-9][a-zA-Z0-9\-]{1,39})\/)?(?P<repo>[\w\-\.]{1,100})#(?P<number>[0-9]+)"
)


CODE_BLOCK_RE = re.compile(
    r"^`([^`\n]+)`" r"|```(.+?)```",  # Inline codeblock  # Multiline codeblock
    re.DOTALL | re.MULTILINE,
)

log = get_logger(__name__)


class RepoTarget(NamedTuple):
    """Used for the repo and user injection."""

    user: str
    repo: str


@dataclass
class FoundIssue:
    """Dataclass representing an issue found by the regex."""

    organisation: Optional[str]
    repository: str
    number: str

    def __hash__(self) -> int:
        return hash((self.organisation, self.repository, self.number))


@dataclass
class FetchError:
    """Dataclass representing an error while fetching an issue."""

    return_code: int
    message: str


@dataclass
class IssueState:
    """Dataclass representing the state of an issue."""

    repository: str
    number: int
    url: str
    title: str
    emoji: str


def whitelisted_autolink() -> Callable[[commands.Command], commands.Command]:
    """Decorator to whitelist a guild for automatic linking."""

    async def predicate(ctx: commands.Context) -> bool:
        cog: "GithubInfo" = ctx.bot.get_cog("GithubInfo")
        user, _ = await cog.fetch_user_and_repo(ctx.message)
        return bool(user)

    return commands.check(predicate)


class GithubCache:
    """Manages the cache of github requests and uses the ETag header to ensure data is always up to date."""

    def __init__(self):
        # todo: possibly store all of this in redis
        self._memcache: cachingutils.MemoryCache[str, tuple[Optional[str], Any]] = cachingutils.MemoryCache(
            timeout=timedelta(hours=3)
        )

        session = cachingutils.redis.async_session(constants.Client.redis_prefix)
        self._rediscache = cachingutils.redis.AsyncRedisCache(prefix="github-api:", session=session._redis)

        self._redis_timeout = timedelta(hours=8).total_seconds()
        self._locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    async def get(
        self, key: str, default: Optional[tuple[Optional[str], Any]] = None
    ) -> Optional[tuple[Optional[str], Any]]:
        """Get the provided key from the internal caches."""
        # only requests for repos go to redis
        if "/repos?" in key:
            return await self._rediscache.get(key, default=default)
        return self._memcache.get(key, default=default)

    async def set(self, key: str, value: Tuple[Optional[str], Any], *, timeout: Optional[float] = None) -> None:
        """Set the provided key and value into the internal caches."""
        if "/repos?" in key:
            return await self._rediscache.set(key, value=value, timeout=timeout or self._redis_timeout)
        return self._memcache.set(key, value=value, timeout=timeout)

    @contextlib.asynccontextmanager
    async def lock(self, key: str) -> AsyncGenerator[None, None]:
        """Runs a lock with the provided key."""
        if key not in self._locks:
            lock = asyncio.Lock()
            self._locks[key] = lock
        else:
            lock = self._locks[key]

        async with lock:
            yield


class GithubInfo(commands.Cog, slash_command_attrs={"dm_permission": False}):
    """Fetches info from GitHub."""

    def __init__(self, bot: Monty):
        self.bot = bot

        transport = AIOHTTPTransport(url="https://api.github.com/graphql", timeout=20, headers=GITHUB_HEADERS)

        self.gql = gql.Client(transport=transport, fetch_schema_from_transport=True)

        # this is a memory cache for most requests, but a redis cache will be used for the list of repos
        self.request_cache: GithubCache = GithubCache()
        self.autolink_cache: cachingutils.MemoryCache[
            int, Tuple[disnake.Message, List[FoundIssue]]
        ] = cachingutils.MemoryCache(timeout=600)

        self.guilds: Dict[str, str] = {}

    async def cog_load(self) -> None:
        """Fetch the gql schema from github."""
        # todo: cache the schema in redis and load from there
        async with self.gql:
            pass

    async def fetch_guild_to_org(self, guild_id: int) -> Optional[str]:
        """Fetch the org that matches to a specific guild_id."""
        guild_config = self.bot.guild_configs.get(guild_id) or await GuildConfig.objects.get_or_none(id=guild_id)
        return guild_config and guild_config.github_issues_org

    async def fetch_data(self, url: str, *, as_text: bool = False, **kw) -> Union[dict[str, Any], str, list[Any], Any]:
        """Retrieve data as a dictionary and cache it, using the provided etag."""
        if "headers" in kw:
            og = kw["headers"]
            kw["headers"] = REQUEST_HEADERS.copy()
            kw["headers"].update(og)
        else:
            kw["headers"] = REQUEST_HEADERS.copy()

        async with self.request_cache.lock(url):
            cached = await self.request_cache.get(url)
            if cached:
                etag, body = cached
                if not etag:
                    # shortcut the return
                    return body
                kw["headers"]["If-None-Match"] = etag
            else:
                etag = None
                body = None

            async with self.bot.http_session.get(url, **kw) as r:
                etag = r.headers.get("ETag")
                if r.status == 304:
                    return body
                if as_text:
                    body = await r.text()
                else:
                    body = await r.json()

                # only cache if etag is provided and the request was in the 200
                if etag and 200 <= r.status < 300:
                    await self.request_cache.set(url, (etag, body))
                elif "/repos?" in url:
                    await self.request_cache.set(url, (None, body), timeout=timedelta(minutes=30).total_seconds())
                return body

    @redis_cache(
        "github-user-repos",
        key_func=lambda user: user,
        timeout=timedelta(hours=8),
        include_posargs=[1],
        include_kwargs=["user"],
        allow_unset=True,
    )
    async def fetch_repos(self, user: str) -> dict[str, str]:
        """Returns the first 100 repos for a user, a dict format."""
        url = ORG_REPOS_ENDPOINT.format(org=user)
        resp: list[Any] = await self.fetch_data(url)  # type: ignore
        if isinstance(resp, dict) and resp.get("message"):
            url = USER_REPOS_ENDPOINT.format(user=user)
            resp: list[Any] = await self.fetch_data(url)  # type: ignore

        repos = {}
        for repo in resp:
            name = repo["name"]
            repos[name.lower()] = name

        return repos

    @overload
    async def fetch_user_and_repo(  # noqa: D102
        self,
        inter: Union[disnake.CommandInteraction, disnake.Message],
        repo: Optional[str] = None,
        user: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        ...

    @overload
    async def fetch_user_and_repo(  # noqa: D102
        self,
        inter: Union[disnake.CommandInteraction, disnake.Message],
        repo: str,
        user: Optional[str] = None,
    ) -> RepoTarget:
        ...

    async def fetch_user_and_repo(  # type: ignore
        self,
        inter: Union[disnake.CommandInteraction, disnake.Message],
        repo: Optional[str] = None,
        user: Optional[str] = None,
    ) -> RepoTarget:
        """
        Adds a user and repo parameter to all slash commands.

        Parameters
        ----------
        user: The user to get repositories for.
        repo: The repository to fetch.
        """
        # todo: get from the database
        guild_id = inter.guild_id if isinstance(inter, disnake.Interaction) else (inter.guild and inter.guild.id)
        if guild_id:
            user = user or await self.fetch_guild_to_org(guild_id)

        if not user:
            raise commands.UserInputError("user must be provided" " or configured for this guild." if guild_id else ".")

        return RepoTarget(user, repo)  # type: ignore

    # this should be a decorator but the typing is a bit scuffed on it right now
    commands.register_injection(fetch_user_and_repo)

    @commands.group(name="github", aliases=("gh", "git"), invoke_without_command=True)
    @commands.cooldown(3, 20, commands.BucketType.user)
    async def github_group(self, ctx: commands.Context) -> None:
        """Commands for finding information related to GitHub."""
        await invoke_help_command(ctx)

    @github_group.command(name="user", aliases=("userinfo",))
    async def github_user_info(self, ctx: commands.Context, username: str) -> None:
        """Fetches a user's GitHub information."""
        async with ctx.typing():
            user_data: dict[str, Any] = await self.fetch_data(
                f"{GITHUB_API_URL}/users/{quote_plus(username)}",
                headers=REQUEST_HEADERS,
            )  # type: ignore

            # User_data will not have a message key if the user exists
            if "message" in user_data:
                embed = disnake.Embed(
                    title=random.choice(constants.NEGATIVE_REPLIES),
                    description=f"The profile for `{username}` was not found.",
                    colour=constants.Colours.soft_red,
                )

                components = DeleteButton(ctx.author, initial_message=ctx.message)
                await ctx.send(embed=embed, components=components)
                return

            org_data: list[dict[str, Any]] = await self.fetch_data(
                user_data["organizations_url"],
                headers=REQUEST_HEADERS,
            )  # type: ignore
            orgs = [f"[{org['login']}](https://github.com/{org['login']})" for org in org_data]
            orgs_to_add = " | ".join(orgs)

            gists = user_data["public_gists"]

            # Forming blog link
            if re.match(r"^https?:\/\/", user_data["blog"]):  # Blog link is complete
                blog = user_data["blog"]
            elif user_data["blog"]:  # Blog exists but the link is not complete
                blog = f"https://{user_data['blog']}"
            else:
                blog = "No website link available."

            html_url = user_data["html_url"]
            embed = disnake.Embed(
                title=f"`{user_data['login']}`'s GitHub profile info",
                description=f"```{user_data['bio']}```\n" if user_data["bio"] else "",
                colour=disnake.Colour.blurple(),
                url=html_url,
                timestamp=datetime.strptime(user_data["created_at"], "%Y-%m-%dT%H:%M:%SZ"),
            )
            embed.set_thumbnail(url=user_data["avatar_url"])
            embed.set_footer(text="Account created at")

            if user_data["type"] == "User":

                embed.add_field(
                    name="Followers",
                    value=f"[{user_data['followers']}]({user_data['html_url']}?tab=followers)",
                    inline=True,
                )
                embed.add_field(
                    name="Following",
                    value=f"[{user_data['following']}]({user_data['html_url']}?tab=following)",
                    inline=True,
                )

            embed.add_field(
                name="Public repos",
                value=f"[{user_data['public_repos']}]({user_data['html_url']}?tab=repositories)",
            )

            if user_data["type"] == "User":
                embed.add_field(
                    name="Gists",
                    value=f"[{gists}](https://gist.github.com/{quote_plus(username, safe='')})",
                )

                embed.add_field(
                    name=f"Organization{'s' if len(orgs)!=1 else ''}",
                    value=orgs_to_add if orgs else "No organizations.",
                )
            embed.add_field(name="Website", value=blog)

            components = [
                DeleteButton(ctx.author, initial_message=ctx.message),
                disnake.ui.Button(style=disnake.ButtonStyle.link, url=html_url, label="Go to Github"),
            ]
        await ctx.send(embed=embed, components=components)

    @github_group.command(name="repository", aliases=("repo",), root_aliases=("repo",))
    async def github_repo_info(self, ctx: commands.Context, *repo: str) -> None:
        """
        Fetches a repositories' GitHub information.

        The repository should look like `user/reponame` or `user reponame`.
        """
        repo: str = "/".join(repo)
        if repo.count("/") != 1:
            embed = disnake.Embed(
                title=random.choice(constants.NEGATIVE_REPLIES),
                description="The repository should look like `user/reponame` or `user reponame`.",
                colour=constants.Colours.soft_red,
            )

            components = DeleteButton(ctx.author, initial_message=ctx.message)
            await ctx.send(embed=embed, components=components)
            return

        async with ctx.typing():
            repo_data: dict[str, Any] = await self.fetch_data(
                f"{GITHUB_API_URL}/repos/{quote(repo)}",
                headers=REQUEST_HEADERS,
            )  # type: ignore

            # There won't be a message key if this repo exists
            if "message" in repo_data:
                embed = disnake.Embed(
                    title=random.choice(constants.NEGATIVE_REPLIES),
                    description="The requested repository was not found.",
                    colour=constants.Colours.soft_red,
                )
                components = DeleteButton(ctx.author, initial_message=ctx.message)
                await ctx.send(embed=embed, components=components)
                return

        html_url = repo_data["html_url"]
        description = repo_data["description"]
        embed = disnake.Embed(
            title=repo_data["name"],
            colour=disnake.Colour.blurple(),
            url=html_url,
        )

        # If it's a fork, then it will have a parent key
        try:
            parent = repo_data["parent"]
            description += f"\n\nForked from [{parent['full_name']}]({parent['html_url']})"
        except KeyError:
            log.debug("Repository is not a fork.")

        embed.description = description
        repo_owner = repo_data["owner"]

        embed.set_author(
            name=repo_owner["login"],
            url=repo_owner["html_url"],
            icon_url=repo_owner["avatar_url"],
        )

        repo_created_at = datetime.strptime(repo_data["created_at"], "%Y-%m-%dT%H:%M:%SZ").strftime("%d/%m/%Y")
        last_pushed = datetime.strptime(repo_data["pushed_at"], "%Y-%m-%dT%H:%M:%SZ").strftime("%d/%m/%Y at %H:%M")

        embed.set_footer(
            text=(
                f"{repo_data['forks_count']} ⑂ "
                f"• {repo_data['stargazers_count']} ⭐ "
                f"• Created At {repo_created_at} "
                f"• Last Commit {last_pushed}"
            )
        )

        components = [
            DeleteButton(ctx.author, initial_message=ctx.message),
            disnake.ui.Button(style=disnake.ButtonStyle.link, url=html_url, label="Go to Github"),
        ]

        await ctx.send(embed=embed, components=components)

    @staticmethod
    def remove_codeblocks(message: str) -> str:
        """Remove any codeblock in a message."""
        return re.sub(CODE_BLOCK_RE, "", message)

    async def fetch_issues(
        self, number: int, repository: str, user: str, gql_opt_in: bool = False
    ) -> Union[IssueState, FetchError]:
        """
        Retrieve an issue from a GitHub repository.

        Returns IssueState on success, FetchError on failure.
        """
        url = ISSUE_ENDPOINT.format(user=user, repository=repository, number=number)

        json_data: dict[str, Any] = await self.fetch_data(url, headers=GITHUB_HEADERS)  # type: ignore

        is_discussion: bool = False
        if "message" in json_data:
            # fetch with gql
            # no caching right now, and only enabled in the disnake guild
            if not gql_opt_in:
                return FetchError(-1, "Issue not found.")
            query = gql.gql(
                """
                query getDiscussion($user: String!, $repository: String!, $number: Int!) {
                    repository(followRenames: true, owner: $user, name: $repository) {
                        discussion(number: $number) {
                            id
                            title
                            answer {
                                id
                            }
                            url
                        }
                    }
                }
                """
            )
            try:
                json_data = await self.gql.execute_async(
                    query,
                    variable_values={
                        "user": user,
                        "repository": repository,
                        "number": number,
                    },
                )
            except (TransportError, TransportQueryError):
                return FetchError(-1, "Issue not found.")

            json_data = json_data["repository"]["discussion"]
            is_discussion = True
        # Since all pulls are issues, all of the data exists as a result of an issue request
        # This means that we don't need to make a second request, since the necessary data
        # of if the pull was merged or not is returned in the json body under pull_request.merged_at
        # If the 'pull_request' key is contained in the API response and there is no error code, then
        # we know that a PR has been requested and a call to the pulls API endpoint may be necessary
        # to get the desired information for the PR.
        if pull_data := json_data.get("pull_request"):
            issue_url = pull_data["html_url"]
            # When 'merged_at' is not None, this means that the state of the PR is merged
            if pull_data["merged_at"] is not None:
                emoji = constants.Emojis.pull_request_merged
            elif json_data["state"] == "closed":
                emoji = constants.Emojis.pull_request_closed
            elif json_data["draft"]:
                emoji = constants.Emojis.pull_request_draft
            else:
                emoji = constants.Emojis.pull_request_open
        elif is_discussion:
            issue_url = json_data["url"]
            if json_data.get("answer"):
                emoji = constants.Emojis.discussion_answered
            else:
                emoji = constants.Emojis.issue_draft
        else:
            # this is a definite issue and not a pull request, and should be treated as such
            issue_url = json_data["html_url"]
            if json_data.get("state") == "open":
                emoji = constants.Emojis.issue_open
            elif (reason := json_data.get("state_reason")) == "not_planned":
                emoji = constants.Emojis.issue_closed_unplanned
            elif reason == "completed":
                emoji = constants.Emojis.issue_closed_completed
            else:
                emoji = constants.Emojis.issue_closed

        return IssueState(repository, number, issue_url, json_data.get("title", ""), emoji)

    @staticmethod
    def format_embed(
        results: Union[list[Union[IssueState, FetchError]], list[IssueState]],
    ) -> disnake.Embed:
        """Take a list of IssueState or FetchError and format a Discord embed for them."""
        description_list = []

        for result in results:
            if isinstance(result, IssueState):
                description_list.append(f"{result.emoji} [\\(#{result.number}\\) {result.title}]({result.url})")
            elif isinstance(result, FetchError):
                description_list.append(f":x: [{result.return_code}] {result.message}")
            else:
                description_list.append("Something internal went wrong.")

        resp = disnake.Embed(colour=constants.Colours.bright_green, description="\n".join(description_list))

        resp.set_author(name="GitHub")
        return resp

    @github_group.group(name="issue", aliases=("pr", "pull"), invoke_without_command=True, case_insensitive=True)
    async def github_issue(
        self,
        ctx: Union[commands.Context, disnake.CommandInteraction],
        numbers: commands.Greedy[int],
        repo: str,
        user: Optional[str] = None,
    ) -> None:
        """Command to retrieve issue(s) from a GitHub repository."""
        if not user or not repo:
            user, repo = await self.fetch_user_and_repo(
                ctx.message if isinstance(ctx, commands.Context) else ctx, user, repo
            )  # type: ignore
            if not user or not repo:
                if not user:
                    if not repo:
                        # both are non-existant
                        raise commands.CommandError("Both a user and repo must be provided.")
                    # user is non-existant
                    raise commands.CommandError("No user provided, a user must be provided.")
                # repo is non-existant
                raise commands.CommandError("No repo provided, a repo must be provided.")
        # Remove duplicates and sort
        numbers = dict.fromkeys(numbers)

        # check if its empty, send help if it is
        if len(numbers) == 0:
            await invoke_help_command(ctx)
            return

        components = DeleteButton(
            ctx.author, initial_message=ctx.message if isinstance(ctx, commands.Context) else None
        )

        if len(numbers) > MAXIMUM_ISSUES:
            embed = disnake.Embed(
                title=random.choice(constants.ERROR_REPLIES),
                color=constants.Colours.soft_red,
                description=f"Too many issues/PRs! (maximum of {MAXIMUM_ISSUES})",
            )
            await ctx.send(embed=embed, components=components)
            if isinstance(ctx, commands.Context):
                await invoke_help_command(ctx)
            return

        results = [await self.fetch_issues(number, repo, user) for number in numbers]
        await ctx.send(embed=self.format_embed(results), components=components)

    @commands.Cog.listener("on_message")
    async def on_message_automatic_issue_link(self, message: disnake.Message) -> None:
        """
        Automatic issue linking.

        Listener to retrieve issue(s) from a GitHub repository using automatic linking if matching <org>/<repo>#<issue>.
        """
        # Ignore bots but NOT webhooks owned by crosschat which also aren't the application id
        # this allows webhooks that are owned by crosschat but aren't application responses
        if message.author.bot and not (
            message.webhook_id and message.application_id == CROSSCHAT_BOT and message.webhook_id != CROSSCHAT_BOT
        ):
            return

        if not message.guild:
            return

        perms = message.channel.permissions_for(message.guild.me)
        if isinstance(message.channel, disnake.Thread):
            req_perm = "send_messages_in_threads"
        else:
            req_perm = "send_messages"
        if not getattr(perms, req_perm):
            return

        default_user: Optional[str] = ""

        issues: List[FoundIssue] = []
        for match in AUTOMATIC_REGEX.finditer(self.remove_codeblocks(message.content)):
            repo = match.group("repo").lower()
            if not (org := match.group("org")):
                if not default_user:
                    if default_user == "":
                        try:
                            default_user, _ = await self.fetch_user_and_repo(message)
                        except commands.UserInputError:
                            continue
                        else:
                            default_user = default_user or None
                    if default_user is None:
                        continue
                org = default_user
                repos = await self.fetch_repos(org)
                if repo not in repos:
                    continue
                repo = repos[repo]

            issues.append(FoundIssue(org, repo, match.group("number")))

        links: list[IssueState] = []

        if issues:

            log.trace(f"Found {issues = }")
            # Remove duplicates
            issues = list(dict.fromkeys(issues, None))

            if len(issues) > MAXIMUM_ISSUES:
                embed = disnake.Embed(
                    title=random.choice(constants.ERROR_REPLIES),
                    color=constants.Colours.soft_red,
                    description=f"Too many issues/PRs! (maximum of {MAXIMUM_ISSUES})",
                )

                components = DeleteButton(message.author)
                await message.channel.send(embed=embed, components=components)
                return

            for repo_issue in issues:
                if repo_issue.organisation is None:
                    continue

                result = await self.fetch_issues(
                    int(repo_issue.number),
                    repo_issue.repository,
                    repo_issue.organisation,
                    gql_opt_in=message.guild.id in (constants.Guilds.disnake, constants.Guilds.testing),
                )
                if isinstance(result, IssueState):
                    links.append(result)

        if not links:
            return

        embed = self.format_embed(links)
        log.debug(f"Sending github issues to {message.channel} in guild {message.guild}.")
        components = DeleteButton(message.author)
        response = await message.channel.send(embed=embed, components=components)
        self.autolink_cache.set(message.id, (response, issues))

    @commands.Cog.listener("on_message_edit")
    async def on_message_edit_automatic_issue_link(self, before: disnake.Message, after: disnake.Message) -> None:
        """Update the list of messages if the original message was edited."""
        if before.content == after.content:
            return

        if not after.guild:
            return

        try:
            sent_msg, before_issues = self.autolink_cache[after.id]
        except KeyError:
            return

        default_user: Optional[str] = ""

        after_issues: List[FoundIssue] = []
        for match in AUTOMATIC_REGEX.finditer(self.remove_codeblocks(after.content)):
            repo = match.group("repo").lower()
            if not (org := match.group("org")):
                if not default_user:
                    if default_user == "":
                        default_user, _ = await self.fetch_user_and_repo(after)
                        default_user = default_user or None
                    if default_user is None:
                        continue
                org = default_user
                repos = await self.fetch_repos(org)
                if repo not in repos:
                    continue
                repo = repos[repo]

            after_issues.append(FoundIssue(org, repo, match.group("number")))

        # if a user provides too many issues here, just forgo it
        after_issues = after_issues[:MAXIMUM_ISSUES]

        if before_issues == after_issues:
            return

        if not after_issues:
            # while we could delete the issue response, I don't think its necessary
            # there is a delete button on it, and anyone who has perms and
            # wants to delete it can press the button
            # we're also still keeping the message in the cache for the time being
            # as I don't see a reason to remove it
            self.autolink_cache.set(after.id, (sent_msg, []))
            # the one thing here is that we're keeping old functionality
            # messages were able to be edited to have their issue links removed
            # and we should continue to support that.
            return

        links: List[IssueState] = []
        for repo_issue in after_issues:
            if repo_issue.organisation is None:
                continue

            result = await self.fetch_issues(
                int(repo_issue.number),
                repo_issue.repository,
                repo_issue.organisation,
                gql_opt_in=after.guild.id in (constants.Guilds.disnake, constants.Guilds.testing),
            )
            if isinstance(result, IssueState):
                links.append(result)

        if not links:
            # see above comments
            return

        embed = self.format_embed(links)

        try:
            await sent_msg.edit(embed=embed)
        except disnake.HTTPException:
            del self.autolink_cache[after.id]
            return

        # update the cache time
        self.autolink_cache.set(after.id, (sent_msg, after_issues))

    @commands.Cog.listener("on_message_delete")
    async def on_message_delete(self, message: disnake.Message) -> None:
        """Clear the message from the cache."""
        # todo: refactor the cache to prune itself *somehow*
        try:
            del self.autolink_cache[message.id]
        except KeyError:
            pass

    @commands.slash_command()
    async def github(self, inter: disnake.ApplicationCommandInteraction) -> None:
        """Helpful commands for viewing information about whitelisted guild's github projects."""
        pass

    @github.sub_command("pull")
    async def github_pull_slash(
        self, inter: disnake.ApplicationCommandInteraction, num: int, repository: RepoTarget
    ) -> None:
        """
        Get information about a provided pull request.

        Parameters
        ----------
        num: the number of the pull request
        repo: the repo to get the pull request from
        """
        user, repo = repository.user, repository.repo
        repo = repo and repo.rsplit("/", 1)[-1]
        await self.github_issue(inter, [num], repo=repo, user=user)

    @github.sub_command("issue")
    async def github_issue_slash(
        self, inter: disnake.ApplicationCommandInteraction, num: int, repo_user: RepoTarget
    ) -> None:
        """
        Get information about a provided issue.

        Parameters
        ----------
        num: the number of the issue
        repo: the repo to get the issue from
        """
        user, repo = repo_user
        repo = repo and repo.rsplit("/", 1)[-1]
        await self.github_issue(inter, numbers=[num], repo=repo, user=user)  # type: ignore


def setup(bot: Monty) -> None:
    """Load the GithubInfo cog."""
    bot.add_cog(GithubInfo(bot))
