import base64
import enum
import itertools
import random
import re
from dataclasses import dataclass
from datetime import timedelta, timezone
from typing import Any, NamedTuple, TypeVar
from urllib.parse import quote, quote_plus

import attrs
import cachingutils
import cachingutils.redis
import disnake
import gql
import gql.client
import mistune
import msgpack
import yarl
from disnake.ext import commands
from gql.transport.aiohttp import AIOHTTPTransport
from gql.transport.exceptions import TransportError, TransportQueryError

import monty.utils.services
from monty import constants
from monty.aiohttp_session import session_args_for_proxy
from monty.bot import Monty
from monty.constants import Feature
from monty.errors import MontyCommandError
from monty.log import get_logger
from monty.utils import responses, scheduling
from monty.utils.caching import redis_cache
from monty.utils.extensions import invoke_help_command
from monty.utils.helpers import fromisoformat, get_num_suffix
from monty.utils.markdown import DiscordRenderer, remove_codeblocks
from monty.utils.messages import DeleteButton, extract_urls, suppress_embeds
from monty.utils.services import GITHUB_REQUEST_HEADERS


KT = TypeVar("KT")
VT = TypeVar("VT")

BAD_RESPONSE = {
    404: "Object not located! Please enter a valid number!",
}


GITHUB_API_URL = "https://api.github.com"

RATE_LIMIT_ENDPOINT = f"{GITHUB_API_URL}/rate_limit"
ORG_REPOS_ENDPOINT = f"{GITHUB_API_URL}/orgs/{{org}}/repos?per_page=100&type=public"
USER_REPOS_ENDPOINT = f"{GITHUB_API_URL}/users/{{user}}/repos?per_page=100&type=public"
ISSUE_ENDPOINT = f"{GITHUB_API_URL}/repos/{{user}}/{{repository}}/issues/{{number}}"
PR_ENDPOINT = f"{GITHUB_API_URL}/repos/{{user}}/{{repository}}/pulls/{{number}}"
LIST_PULLS_ENDPOINT = f"{GITHUB_API_URL}/repos/{{user}}/{{repository}}/pulls?per_page=100"
LIST_ISSUES_ENDPOINT = f"{GITHUB_API_URL}/repos/{{user}}/{{repository}}/issues?per_page=100"
ISSUE_COMMENT_ENDPOINT = f"{GITHUB_API_URL}/repos/{{user}}/{{repository}}/issues/comments/{{comment_id}}"
PULL_REVIEW_ENDPOINT = f"{GITHUB_API_URL}/repos/{{user}}/{{repository}}/pulls/{{number}}/reviews/{{review_id}}"
PULL_REVIEW_COMMENT_ENDPOINT = f"{GITHUB_API_URL}/repos/{{user}}/{{repository}}/pulls/comments/{{comment_id}}"


# Maximum number of issues in one message
MAXIMUM_ISSUES = 6

# Regex used when looking for automatic linking in messages
# regex101 of current regex https://regex101.com/r/V2ji8M/6
AUTOMATIC_REGEX = re.compile(
    r"((?P<org>[a-zA-Z0-9][a-zA-Z0-9\-]{1,39})\/)?(?P<repo>[\w\-\.]{1,100})#(?P<number>[0-9]+)"
)

# note, this should only be used with re.fullmatch
GITHUB_ISSUE_LINK_REGEX = re.compile(
    # match repo owner and repo name
    r"https?:\/\/github.com\/(?P<org>[a-zA-Z0-9][a-zA-Z0-9\-]{1,39})\/(?P<repo>[\w\-\.]{1,100})\/"
    # match `issues`/`pull`/`discussion`, the ID, and allow a `/files` suffix if there was a `pull`
    r"(?P<type>issues|(?P<ispull>pull)|discussions)\/(?P<number>[0-9]+)(?(ispull)\/files)?"
    # ensure the url path ends at this point and that only a query/fragment follows, if any
    r"\/?([\?#]\S*)?"
)


# eventually these will replace the above
EXPAND_ISSUE_CUSTOM_ID_PREFIX = "gh:issue-expand-v1:"
EXPAND_ISSUE_CUSTOM_ID_FORMAT = EXPAND_ISSUE_CUSTOM_ID_PREFIX + r"{user_id}:{state}:{org}/{repo}#{num}"
EXPAND_ISSUE_CUSTOM_ID_REGEX = re.compile(
    re.escape(EXPAND_ISSUE_CUSTOM_ID_PREFIX)
    # 1 is expanded, 0 is collapsed
    + r"(?P<user_id>[0-9]+):(?P<current_state>0|1):"
    r"(?P<org>[a-zA-Z0-9][a-zA-Z0-9\-]{1,39})\/(?P<repo>[\w\-\.]{1,100})#(?P<number>[0-9]+)"
)

DISCUSSION_GRAPHQL_QUERY = gql.gql(
    """
    query getDiscussion($user: String!, $repository: String!, $number: Int!) {
        repository(followRenames: true, owner: $user, name: $repository) {
            discussion(number: $number) {
                id
                html_url: url
                title
                body
                created_at: createdAt
                user: author {
                    login
                    html_url: url
                    avatar_url: avatarUrl
                }
                labels(first: 20) {
                    nodes {
                        name
                    }
                }
                answer {
                    id
                }
            }
        }
    }
"""
)
DISCUSSION_COMMENT_GRAPHQL_QUERY = gql.gql(
    """
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
)

log = get_logger(__name__)


class RepoTarget(NamedTuple):
    """Used for the repo and user injection."""

    user: str
    repo: str


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


class IssueSourceFormat(enum.IntEnum):
    github_form_with_repo = enum.auto()  # DisnakeDev/disnake#459
    direct_github_url = enum.auto()  # https://github.com/DisnakeDev/disnake/issues/459
    monty_swap_state_button = enum.auto()  # see EXPAND_ISSUE_CUSTOM_ID_PREFIX


@dataclass
class FoundIssue:
    """Dataclass representing an issue found by the regex."""

    organisation: str | None
    repository: str
    number: str
    source_format: IssueSourceFormat
    url_fragment: str = ""
    user_url: str | None = None
    is_discussion: bool | None = None  # `None` means uncertain

    def __hash__(self) -> int:
        return hash((self.organisation, self.repository, self.number))

    def has_comment_fragment(self) -> bool:
        """Returns true if `url_fragment` is set and doesn't point to a top-level resource."""
        return bool(self.url_fragment and not self.url_fragment.startswith(("issue-", "discussion-")))


@dataclass
class FetchError:
    """Dataclass representing an error while fetching an issue."""

    return_code: int
    message: str


@dataclass
class IssueState:
    """Dataclass representing the state of an issue."""

    organisation: str
    repository: str
    number: int
    url: str
    title: str
    emoji: str
    raw_json: dict[str, Any] | None = None


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

        transport = AIOHTTPTransport(
            url="https://api.github.com/graphql",
            timeout=20,
            headers=GITHUB_REQUEST_HEADERS,
            # copy because invariance
            client_session_args=dict(session_args_for_proxy(bot.http.proxy)),
        )

        self.gql_client = gql.Client(transport=transport, fetch_schema_from_transport=True)

        # this is a memory cache for most requests, but a redis cache will be used for the list of repos
        self.autolink_cache: cachingutils.MemoryCache[int, tuple[disnake.Message, list[FoundIssue]]] = (
            cachingutils.MemoryCache(timeout=600)
        )

        self.guilds: dict[str, str] = {}

    async def cog_load(self) -> None:
        """
        Run initial fetch commands upon loading.

        Sync the Ratelimit object, and more.
        Fetch the graphQL schema from GitHub.
        """
        await self._fetch_and_update_ratelimits()

        # TODO: cache the schema in redis and load from there
        self.gql = await self.gql_client.connect_async(reconnecting=True)

    def cog_unload(self) -> None:
        """Close gql session upon unloading cog."""
        scheduling.create_task(self.gql_client.close_async(), name="gql client close")

    async def _fetch_and_update_ratelimits(self) -> None:
        # this is NOT using fetch_data because we need to check the status code.
        async with self.bot.http_session.get(RATE_LIMIT_ENDPOINT, headers=GITHUB_REQUEST_HEADERS) as r:
            # the Rate_limit endpoint is not ratelimited
            if r.status == 403 or r.status >= 500 or r.status == 401:
                return

            data = await r.json()

        monty.utils.services.update_github_ratelimits_from_ratelimit_page(data)  # type: ignore

    async def fetch_guild_to_org(self, guild_id: int) -> str | None:
        """Fetch the org that matches to a specific guild_id."""
        guild_config = await self.bot.ensure_guild_config(guild_id)
        return guild_config and guild_config.github_issues_org

    async def fetch_data(
        self, url: str, *, method: str = "GET", as_text: bool = False, **kw
    ) -> dict[str, Any] | str | list[Any] | Any:
        """Fetch the data from GitHub. Shortcut method to not require multiple context managers."""
        if "headers" in kw:
            og = kw["headers"]
            kw["headers"] = GITHUB_REQUEST_HEADERS.copy()
            kw["headers"].update(og)
        else:
            kw["headers"] = GITHUB_REQUEST_HEADERS.copy()

        method = method.upper().strip()
        async with self.bot.http_session.request(method, url, **kw) as r:
            monty.utils.services.update_github_ratelimits_on_request(r)
            if as_text:
                return await r.text()
            else:
                return await r.json()

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
        resp: list[Any] = await self.fetch_data(url, use_cache=False)  # type: ignore
        if isinstance(resp, dict) and resp.get("message"):
            url = USER_REPOS_ENDPOINT.format(user=user)
            resp: list[Any] = await self.fetch_data(url, use_cache=False)  # type: ignore

        repos = {}
        for repo in resp:
            name = repo["name"]
            repos[name.lower()] = name

        return repos

    async def fetch_user_and_repo(  # type: ignore
        self,
        guild_id: int | None,
        repo: str | None = None,
        user: str | None = None,
    ) -> RepoTarget:
        """
        Adds a user and repo parameter to all slash commands.

        Parameters
        ----------
        user: The user to get repositories for.
        repo: The repository to fetch.
        """
        # TODO: get from the database
        if guild_id:
            user = user or await self.fetch_guild_to_org(guild_id)

        if not user:
            raise commands.UserInputError("user must be provided or configured for this guild." if guild_id else ".")

        return RepoTarget(user, repo)  # type: ignore

    @commands.group(name="github", aliases=("gh", "git"), invoke_without_command=True)
    @commands.cooldown(3, 20, commands.BucketType.user)
    async def github_group(self, ctx: commands.Context, user_or_repo: str = "") -> None:
        """Commands for finding information related to GitHub."""
        if not user_or_repo:
            await invoke_help_command(ctx)
            return
        # simplified repo or user syntax here
        if user_or_repo.count("/") > 0:
            await self.github_repo_info(ctx, user_or_repo)
            return
        else:
            await self.github_user_info(ctx, user_or_repo)
            return

    @github_group.command(name="user", aliases=("userinfo",))
    async def github_user_info(self, ctx: commands.Context, username: str) -> None:
        """Fetches a user's GitHub information."""
        async with ctx.typing():
            user_data: dict[str, Any] = await self.fetch_data(
                f"{GITHUB_API_URL}/users/{quote_plus(username)}",
                headers=GITHUB_REQUEST_HEADERS,
            )  # type: ignore

            # User_data will not have a message key if the user exists
            if "message" in user_data:
                msg = f"The profile for `{username}` was not found."
                raise MontyCommandError(msg)

            org_data: list[dict[str, Any]] = await self.fetch_data(
                user_data["organizations_url"],
                headers=GITHUB_REQUEST_HEADERS,
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
                timestamp=fromisoformat(user_data["created_at"]),
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
                    name=f"Organization{'s' if len(orgs) != 1 else ''}",
                    value=orgs_to_add if orgs else "No organizations.",
                )
            embed.add_field(name="Website", value=blog)

            components = [
                DeleteButton(ctx.author, initial_message=ctx.message),
                disnake.ui.Button(style=disnake.ButtonStyle.link, url=html_url, label="Go to Github"),
            ]
        await ctx.send(embed=embed, components=components)

    @github_group.command(name="repository", aliases=("repo",), root_aliases=("repo",))
    async def github_repo_info(self, ctx: commands.Context, *repository: str) -> None:
        """
        Fetches a repositories' GitHub information.

        The repository should look like `user/reponame` or `user reponame`.
        """
        repo_name: str
        if repository[0].count("/"):
            repo_name = repository[0]
        elif len(repository) >= 2:
            repo_name = "/".join(repository[:2])
        else:
            repo_name = ""

        if not repo_name or repo_name.count("/") > 1:
            args = " ".join(repository[:2])

            raise commands.BadArgument(
                "The repository should look like `user/reponame` or `user reponame`"
                + (f", not `{args}`." if "`" not in args and len(args) < 20 else ".")
            )
            return

        async with ctx.typing():
            repo_data: dict[str, Any] = await self.fetch_data(
                f"{GITHUB_API_URL}/repos/{quote(repo_name)}",
                headers=GITHUB_REQUEST_HEADERS,
            )  # type: ignore

            # There won't be a message key if this repo exists
            if "message" in repo_data:
                embed = disnake.Embed(
                    title=random.choice(responses.FAILURE_HEADERS),
                    description="The requested repository was not found.",
                    colour=responses.DEFAULT_FAILURE_COLOUR,
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

        repo_owner = repo_data["owner"]

        embed.set_author(
            name=repo_owner["login"],
            url=repo_owner["html_url"],
            icon_url=repo_owner["avatar_url"],
        )

        repo_created_at = fromisoformat(repo_data["created_at"]).astimezone(timezone.utc).strftime("%d/%m/%Y")
        last_pushed = fromisoformat(repo_data["pushed_at"]).astimezone(timezone.utc).strftime("%d/%m/%Y at %H:%M")

        embed.set_footer(
            text=(
                f"{repo_data['forks_count']} ⑂ "
                f"• {repo_data['stargazers_count']} ⭐ "
                f"• Created At {repo_created_at} "
                f"• Last Commit {last_pushed}"
            )
        )

        # mirrors have a mirror_url key. See google/skia as an example.
        if repo_data.get("mirror_url"):
            mirror_url = repo_data["mirror_url"]
            description += f"\n\nMirrored from <{mirror_url}>."

        embed.description = description

        components = [
            DeleteButton(ctx.author, initial_message=ctx.message),
            disnake.ui.Button(style=disnake.ButtonStyle.link, url=html_url, label="Go to Github"),
        ]

        await ctx.send(embed=embed, components=components)

    async def fetch_issues(
        self,
        number: int,
        repository: str,
        user: str,
        *,
        allow_discussions: bool = False,
        is_discussion: bool | None = None,
    ) -> IssueState | FetchError:
        """
        Retrieve an issue from a GitHub repository.

        Returns IssueState on success, FetchError on failure.
        """
        if not is_discussion:  # not a discussion, or uncertain
            url = ISSUE_ENDPOINT.format(user=user, repository=repository, number=number)
            json_data: dict[str, Any] = await self.fetch_data(url, headers=GITHUB_REQUEST_HEADERS)  # type: ignore

            if "message" in json_data:
                is_discussion = True  # if we got an error, assume it may be a discussion

        if is_discussion:
            # fetch with gql
            # no caching right now, and only enabled in the disnake guild
            if not allow_discussions:
                return FetchError(404, "Issue not found.")

            try:
                json_data = await self.gql.execute(
                    gql.GraphQLRequest(
                        DISCUSSION_GRAPHQL_QUERY,
                        variable_values={
                            "user": user,
                            "repository": repository,
                            "number": number,
                        },
                    )
                )
            except (TransportError, TransportQueryError):
                return FetchError(-1, "Issue not found.")

            json_data = json_data["repository"]["discussion"]

            # shuffle fields around to match issue json structure
            json_data["labels"] = (json_data.get("labels") or {}).get("nodes") or []

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
            issue_url = json_data["html_url"]
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

        return IssueState(
            user,
            repository,
            number,
            issue_url,
            json_data.get("title", ""),
            emoji,
            raw_json=json_data,
        )

    def format_embed_expanded_issue(
        self,
        issue: IssueState,
    ) -> disnake.Embed:
        """Given one issue, format an expanded embed with considerably more detail than usual."""
        if not isinstance(issue, IssueState):
            err = f"issue must be an instance of IssueState, not {type(issue)}"
            raise TypeError(err)
        if not issue.raw_json:
            msg = "the provided issue does not have its raw json payload"
            raise ValueError(msg)

        # NOTE: the fields used here should be available in `DISCUSSION_GRAPHQL_QUERY` as well

        json_data = issue.raw_json
        embed = disnake.Embed(colour=disnake.Colour(0xFFFFFF))
        embed.set_author(
            name=json_data["user"]["login"],
            url=json_data["user"]["html_url"],
            icon_url=json_data["user"]["avatar_url"],
        )
        embed.title = f"{issue.emoji} [{issue.organisation}/{issue.repository}] {issue.title}"

        if json_data["labels"]:
            labels = ", ".join(sorted([label["name"] for label in json_data["labels"]]))
            if len(labels) > 1024:
                labels = labels[:1020] + "..."
            embed.add_field("Labels", labels)

        embed.url = issue.url
        embed.timestamp = fromisoformat(json_data["created_at"])
        embed.set_footer(text="Created ", icon_url=constants.Icons.github_avatar_url)

        body: str | None = json_data["body"]
        if body and not body.isspace():
            # escape wack stuff from the markdown
            embed.description = self.render_github_markdown(
                body, context=RenderContext(user=issue.organisation, repo=issue.repository)
            )
        if not body or body.isspace():
            embed.description = "*No description provided.*"
        return embed

    def format_embed(
        self,
        results: list[IssueState | FetchError] | list[IssueState],
        *,
        expand_one_issue: bool = False,
        show_errors_inline: bool = True,
    ) -> tuple[disnake.Embed, int, bool]:
        """Take a list of IssueState or FetchError and format a Discord embed for them."""
        description_list = []
        if (
            expand_one_issue
            and len(results) == 1
            and isinstance(issue := results[0], IssueState)
            and issue.raw_json is not None
        ):
            # show considerably more information about the issue if there is a single provided issue
            return (self.format_embed_expanded_issue(issue), 1, True)

        issue_count = 0
        for result in results:
            if isinstance(result, IssueState):
                description_list.append(f"{result.emoji} [(#{result.number}) {result.title}]({result.url})")
                issue_count += 1
            elif show_errors_inline:
                if isinstance(result, FetchError):
                    description_list.append(f":x: [{result.return_code}] {result.message}")
                else:
                    description_list.append("Something internal went wrong.")

        if not description_list:
            msg = "must have at least one IssueState if show_errors_inline is enabled"
            raise ValueError(msg)

        resp = disnake.Embed(colour=constants.Colours.bright_green, description="\n".join(description_list))

        resp.set_author(name="GitHub")
        return resp, issue_count, False

    @github_group.group(name="issue", aliases=("pr", "pull"), invoke_without_command=True, case_insensitive=True)
    async def github_issue(
        self,
        ctx: commands.Context | disnake.CommandInteraction,
        numbers: commands.Greedy[int],
        repo: str,
        user: str | None = None,
    ) -> None:
        """Command to retrieve issue(s) from a GitHub repository."""
        if not user or not repo:
            user, repo = await self.fetch_user_and_repo(
                ctx.guild and ctx.guild.id if isinstance(ctx, commands.Context) else ctx.guild_id,
                user,
                repo,
            )  # type: ignore
            if not user or not repo:
                if not user:
                    if not repo:
                        # both are non-existant
                        msg = "Both a user and repo must be provided."
                        raise commands.CommandError(msg)
                    # user is non-existant
                    msg = "No user provided, a user must be provided."
                    raise commands.CommandError(msg)
                # repo is non-existant
                msg = "No repo provided, a repo must be provided."
                raise commands.CommandError(msg)
        # Remove duplicates while maintaining order
        issue_numbers = list(dict.fromkeys(numbers))

        # check if its empty, send help if it is
        if len(issue_numbers) == 0:
            assert isinstance(ctx, commands.Context)
            await invoke_help_command(ctx)
            return

        components = DeleteButton(
            ctx.author, initial_message=ctx.message if isinstance(ctx, commands.Context) else None
        )

        if len(issue_numbers) > MAXIMUM_ISSUES:
            embed = disnake.Embed(
                title=random.choice(responses.USER_INPUT_ERROR_REPLIES),
                color=responses.DEFAULT_FAILURE_COLOUR,
                description=f"Too many issues/PRs! (maximum of {MAXIMUM_ISSUES})",
            )
            await ctx.send(embed=embed, components=components)
            if isinstance(ctx, commands.Context):
                await invoke_help_command(ctx)
            return

        results = [await self.fetch_issues(number, repo, user) for number in issue_numbers]
        expand_one_issue = await self.bot.guild_has_feature(ctx.guild, constants.Feature.GITHUB_ISSUE_EXPAND)
        await ctx.send(embed=self.format_embed(results, expand_one_issue=expand_one_issue)[0], components=components)

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

    async def fetch_default_user(self, guild_id: int) -> str | None:
        """
        Get the default GitHub user in the context of the provided Message.

        Right now this only returns the default user for the message's guild.
        """
        try:
            default_user, _ = await self.fetch_user_and_repo(guild_id)
        except commands.UserInputError:
            return None
        return default_user

    async def extract_issues_from_content(
        self,
        content: str,
        *,
        guild_id: int | None = None,
        extract_full_links: bool = False,
    ) -> list[FoundIssue]:
        """Extract issues in a message into FoundIssues."""
        issues: list[FoundIssue] = []
        default_user: str | None = ""
        stripped_content = remove_codeblocks(content)

        if extract_full_links:
            # this is hacky, but refactored in #228
            links = extract_urls(stripped_content)
            matches = itertools.chain(
                AUTOMATIC_REGEX.finditer(stripped_content),
                filter(None, map(GITHUB_ISSUE_LINK_REGEX.fullmatch, links)),
            )
        else:
            matches = itertools.chain(AUTOMATIC_REGEX.finditer(stripped_content))
        for match in matches:
            fragment = ""
            if match.re is GITHUB_ISSUE_LINK_REGEX:
                source_format = IssueSourceFormat.direct_github_url
                url = yarl.URL(match[0])
                fragment = url.fragment  # used to match for comments later
            else:
                # match.re is AUTOMATIC_REGEX, which doesn't require special handling right now
                source_format = IssueSourceFormat.github_form_with_repo
                url = None

            repo = match.group("repo").lower()
            if not (org := match.group("org")):
                if default_user == "" and guild_id:
                    default_user = await self.fetch_default_user(guild_id)
                if default_user is None:
                    continue
                org = default_user
                repos = await self.fetch_repos(org)
                if repo not in repos:
                    continue
                repo = repos[repo]

            issues.append(
                FoundIssue(
                    org,
                    repo,
                    match.group("number"),
                    source_format=source_format,
                    url_fragment=fragment,
                    user_url=str(url) if url is not None else None,
                    # use groupdict since this group only exists on one of the two regexes
                    is_discussion=match.groupdict().get("type") == "discussions",
                )
            )

        # return a de-duped list
        return list(dict.fromkeys(issues, None))

    def get_current_button_expansion_state(self, custom_id: str) -> bool:
        """Get whether the issue is currently expanded or collapsed."""
        match = EXPAND_ISSUE_CUSTOM_ID_REGEX.fullmatch(custom_id)
        if not match:
            msg = "Invalid custom_id provided."
            raise ValueError(msg)
        return match.group("current_state") == "1"

    def get_expand_button(
        self,
        issues: list[IssueState],
        *,
        is_expanded: bool = False,
        user_id: int,
    ) -> disnake.ui.Button | None:
        """Create a new expand button based on the provided issue, if there is only one issue."""
        if len(issues) != 1:
            return None
        issue = issues[0]
        return disnake.ui.Button(
            style=disnake.ButtonStyle.primary,
            label="Show less" if is_expanded else "Show more",
            custom_id=EXPAND_ISSUE_CUSTOM_ID_FORMAT.format(
                user_id=user_id,
                state=int(is_expanded),
                org=issue.organisation,
                repo=issue.repository,
                num=issue.number,
            ),
        )

    @commands.Cog.listener("on_button_click")
    async def swap_embed_state(self, inter: disnake.MessageInteraction) -> None:
        """Swap the embed state for a larger or smaller embed."""
        # n.b. data integrity is to be managed by any method that edits this message.
        # ensuring this button has the correct ID and only shows up on messages with one issue is vital.
        if not inter.data.custom_id.startswith(EXPAND_ISSUE_CUSTOM_ID_PREFIX):
            return

        match = EXPAND_ISSUE_CUSTOM_ID_REGEX.fullmatch(inter.data.custom_id)
        if not match:
            await inter.response.send_message("Sorry, something went wrong.", ephemeral=True)
            err = f"github issue toggle did not match the regex: {inter.data.custom_id}"
            raise ValueError(err)

        # check the user
        is_expanded = int(match.group("current_state"))
        original_user_id = int(match.group("user_id"))

        is_different_author = original_user_id != inter.author.id
        can_swap_embed = not is_different_author or inter.permissions.manage_messages

        # if the issue is already expanded and not OP (or mod), ignore the interaction
        if is_expanded and not can_swap_embed:
            await inter.response.send_message("Sorry, but you cannot collapse this issue!", ephemeral=True)
            return

        issue = FoundIssue(
            match.group("org"),
            match.group("repo"),
            match.group("number"),
            source_format=IssueSourceFormat.monty_swap_state_button,
        )
        found_issue = await self.fetch_issues(
            int(issue.number),
            issue.repository,
            issue.organisation,  # type: ignore
            allow_discussions=True,  # if we have a discussion linked it was enabled at some point
        )
        embed, *_ = self.format_embed([found_issue], expand_one_issue=not is_expanded)

        # send the embed in a new message
        if not is_expanded and is_different_author:
            await inter.response.send_message(embed=embed, ephemeral=True)
            return

        new_custom_id = EXPAND_ISSUE_CUSTOM_ID_FORMAT.format(
            user_id=original_user_id,
            state=int(not is_expanded),
            org=issue.organisation,
            repo=issue.repository,
            num=issue.number,
        )

        rows = disnake.ui.ActionRow.rows_from_message(inter.message)
        for row in rows:
            for comp in row:
                if comp.custom_id == inter.data.custom_id:
                    comp.custom_id = new_custom_id
                    if is_expanded:
                        comp.label = "Show more"  # type: ignore
                    else:
                        comp.label = "Show less"  # type: ignore
                    break

        await inter.response.edit_message(embed=embed, components=rows)

    async def handle_issue_comment(
        self, message: disnake.Message | disnake.Interaction, issues: list[FoundIssue]
    ) -> None:
        """Expand an issue or pull request comment."""
        comments = []
        components = []

        for issue in issues:
            frag = issue.url_fragment
            assert frag
            expected_url = issue.user_url
            assert expected_url

            comment: dict[str, Any]
            created_at_key = "created_at"
            if frag.startswith("discussioncomment-"):
                global_id = self._format_github_global_id(
                    "DC",
                    # repository ID; doesn't actually appear to
                    # be necessary yet, but this may change in the future
                    0,
                    # comment ID
                    int(frag.removeprefix("discussioncomment-")),
                )

                try:
                    json_data = await self.gql.execute(
                        gql.GraphQLRequest(
                            DISCUSSION_COMMENT_GRAPHQL_QUERY,
                            variable_values={
                                "id": global_id,
                            },
                        )
                    )
                except (TransportError, TransportQueryError) as e:
                    log.warning("encountered error fetching discussion comment: %s", e)
                    continue

                comment = json_data["node"]

            else:
                if frag.startswith("issuecomment-"):
                    endpoint = ISSUE_COMMENT_ENDPOINT.format(
                        user=issue.organisation,
                        repository=issue.repository,
                        comment_id=frag.removeprefix("issuecomment-"),
                    )
                elif frag.startswith("pullrequestreview-"):
                    endpoint = PULL_REVIEW_ENDPOINT.format(
                        user=issue.organisation,
                        repository=issue.repository,
                        number=issue.number,
                        review_id=frag.removeprefix("pullrequestreview-"),
                    )
                    created_at_key = "submitted_at"  # thank you github, very cool
                elif frag.startswith("discussion_r"):
                    endpoint = PULL_REVIEW_COMMENT_ENDPOINT.format(
                        user=issue.organisation,
                        repository=issue.repository,
                        comment_id=frag.removeprefix("discussion_r"),
                    )
                elif re.fullmatch(r"r\d+", frag):
                    # same as the one above
                    endpoint = PULL_REVIEW_COMMENT_ENDPOINT.format(
                        user=issue.organisation,
                        repository=issue.repository,
                        comment_id=frag.removeprefix("r"),
                    )
                    # Linking comments from the "Files" tab of PRs gets you a link like
                    # `pull/1234/files#r12345678`; this is equivalent to the link from the
                    # main "Conversation" tab, which looks like `pull/1234#discussion_r12345678`.
                    # The API always returns links in the latter format, so adjust the user-provided
                    # url here accordingly for the check below.
                    expected_url = yarl.URL(expected_url)
                    expected_url = expected_url.with_path(expected_url.path.rstrip("/files"))
                    expected_url = expected_url.with_fragment(f"discussion_{frag}")
                    expected_url = str(expected_url)
                else:
                    continue

                comment = await self.fetch_data(endpoint, as_text=False)  # type: ignore
                if "message" in comment:
                    log.warning("encountered error fetching %s: %s", endpoint, comment)
                    continue

            # assert the url was not tampered with
            if expected_url != (html_url := comment["html_url"]):
                # this is a warning as its the best way I currently have to track how often the wrong url is used
                log.warning("[comment autolink] issue url %s does not match comment url %s", issue.user_url, html_url)
                continue

            body = self.render_github_markdown(comment["body"])
            e = disnake.Embed(
                url=html_url,
                description=body,
            )

            author = comment["user"]
            e.set_author(
                name=author["login"],
                icon_url=author["avatar_url"],
                url=author["html_url"],
            )

            e.set_footer(text=f"Comment on {issue.organisation}/{issue.repository}#{issue.number}")

            e.timestamp = fromisoformat(comment[created_at_key])

            comments.append(e)
            components.append(disnake.ui.Button(url=comment["html_url"], label="View comment"))

        if not comments:
            return

        if isinstance(message, disnake.Message):
            reply_method = message.reply
        elif isinstance(message, disnake.Interaction):
            reply_method = message.send
        else:
            msg = "unreachable"
            raise RuntimeError(msg)

        if len(comments) > 4:
            await reply_method(
                "Only 4 comments can be expanded at a time. Please send with only four comments if you would like"
                " them to be expanded!",
                components=DeleteButton(message.author),
                allowed_mentions=disnake.AllowedMentions(replied_user=False),
            )
            return

        if (
            isinstance(message, disnake.Message)
            and message.guild
            and message.channel.permissions_for(message.guild.me).manage_messages
        ):
            scheduling.create_task(suppress_embeds(self.bot, message))

        if len(comments) > 1:
            for num, component in enumerate(components, 1):
                suffix = get_num_suffix(num)
                # current implemenation does allow mixing comments and actual issues
                # this will be wrong in that case. Oh well.
                component.label = f"View {num}{suffix} comment"

        components.insert(0, DeleteButton(message.author))
        await reply_method(
            embeds=comments,
            components=components,
            allowed_mentions=disnake.AllowedMentions(replied_user=False),
        )

    @commands.Cog.listener("on_message")
    async def on_message_automatic_issue_link(
        self, message: disnake.Message | disnake.ApplicationCommandInteraction, content: str | None = None
    ) -> None:
        """
        Automatic issue linking.

        Listener to retrieve issue(s) from a GitHub repository using automatic linking if matching <org>/<repo>#<issue>.
        """
        if message.author.bot:
            return

        if isinstance(message, disnake.Message):
            if not message.guild:
                return

            config = await self.bot.ensure_guild_config(message.guild.id)
            if not config.github_issue_linking:
                return

            if message.guild.me:
                perms = message.channel.permissions_for(message.guild.me)
                if isinstance(message.channel, disnake.Thread):
                    has_perm = perms.send_messages_in_threads
                else:
                    has_perm = perms.send_messages
                if not has_perm:
                    return
            else:
                perms = disnake.Permissions.private_channel()

            extract_full_links = await self.bot.guild_has_feature(message.guild, Feature.GITHUB_ISSUE_LINKS)
            guild_id = message.guild.id
            guild_has_github_comment_linking_enabled = config.github_comment_linking
            issues = await self.extract_issues_from_content(
                message.content,
                guild_id=guild_id,
                extract_full_links=extract_full_links,
            )
        elif isinstance(message, disnake.ApplicationCommandInteraction):
            # HACK
            guild_id = message.guild_id  # type: ignore
            perms = message.app_permissions
            extract_full_links = True
            guild_has_github_comment_linking_enabled = True  # we check the feature later

            issues = await self.extract_issues_from_content(
                content or "",
                guild_id=guild_id,
                extract_full_links=extract_full_links,
            )
        else:
            msg = "unreachable"
            raise RuntimeError(msg)

        # no issues found, return early
        if not issues:
            return

        if issue_comments := list(filter(lambda issue: issue.has_comment_fragment(), issues)):
            # if there are issue comments found, we do not want to expand the entire issue
            # we also only want to expand the issue if the feature is enabled
            # AND both options of the guild configuration are enabled
            if guild_has_github_comment_linking_enabled and await self.bot.guild_has_feature(
                guild_id, Feature.GITHUB_COMMENT_LINKS
            ):
                await self.handle_issue_comment(message, issue_comments)
            return

        links: list[IssueState] = []
        log.trace(f"Found {issues = }")

        if len(issues) > MAXIMUM_ISSUES:
            # must be handled here due to local side-effect, for now
            embed = disnake.Embed(
                title=random.choice(responses.USER_INPUT_ERROR_REPLIES),
                color=responses.DEFAULT_FAILURE_COLOUR,
                description=f"Too many issues/PRs! (maximum of {MAXIMUM_ISSUES})",
            )

            components = [DeleteButton(message.author)]
            if isinstance(message, disnake.Message):
                response = await message.channel.send(embed=embed, components=components)
                self.autolink_cache.set(message.id, (response, issues))
            elif isinstance(message, disnake.ApplicationCommandInteraction):
                await message.send(embed=embed, ephemeral=True)
            return

        total_pre_expanded = 0
        for repo_issue in issues:
            if repo_issue.organisation is None:
                continue

            result = await self.fetch_issues(
                int(repo_issue.number),
                repo_issue.repository,
                repo_issue.organisation,
                allow_discussions=await self.bot.guild_has_feature(guild_id, Feature.GITHUB_DISCUSSIONS),
                is_discussion=repo_issue.is_discussion,
            )
            if isinstance(result, IssueState):
                links.append(result)
                if repo_issue.source_format is IssueSourceFormat.direct_github_url:
                    total_pre_expanded += 1

        # for now, we do not expand when there is more than 1 pre-expanded image link
        if total_pre_expanded > 1:
            return

        if not links:
            return

        if len(links) == 1 and issues[0].source_format is IssueSourceFormat.direct_github_url:
            if perms.manage_messages and isinstance(message, disnake.Message):
                scheduling.create_task(suppress_embeds(self.bot, message))
            allow_expand = True
            allow_pre_expanded = True
        else:
            allow_expand = await self.bot.guild_has_feature(guild_id, Feature.GITHUB_ISSUE_EXPAND)
            allow_pre_expanded = False

        embed, _issue_count, was_expanded = self.format_embed(links, expand_one_issue=allow_pre_expanded)
        log.debug(f"Sending GitHub issues to {message.channel} in guild {message.guild}.")
        components: list[disnake.ui.Button] = [DeleteButton(message.author)]
        if allow_expand:
            button = self.get_expand_button(
                links,
                user_id=message.author.id,
                is_expanded=was_expanded,
            )
            if button:
                components.append(button)

        if isinstance(message, disnake.ApplicationCommandInteraction):
            await message.send(embed=embed, components=components)
        else:
            response = await message.reply(
                embed=embed,
                components=components,
                allowed_mentions=disnake.AllowedMentions(replied_user=False),
            )
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

        after_issues = await self.extract_issues_from_content(
            after.content,
            guild_id=after.guild.id,
            extract_full_links=await self.bot.guild_has_feature(after.guild, Feature.GITHUB_ISSUE_LINKS),
        )

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

        links: list[IssueState] = []
        total_pre_expanded = 0
        for repo_issue in after_issues:
            if repo_issue.organisation is None:
                continue

            result = await self.fetch_issues(
                int(repo_issue.number),
                repo_issue.repository,
                repo_issue.organisation,
                allow_discussions=await self.bot.guild_has_feature(after.guild.id, Feature.GITHUB_DISCUSSIONS),
                is_discussion=repo_issue.is_discussion,
            )
            if isinstance(result, IssueState):
                links.append(result)
                if repo_issue.source_format is IssueSourceFormat.direct_github_url:
                    total_pre_expanded += 1

        if not links:
            # see above comments
            return

        allow_expand = await self.bot.guild_has_feature(after.guild, Feature.GITHUB_ISSUE_EXPAND)

        # update the components
        is_expanded = False
        # get existing button
        rows = disnake.ui.ActionRow.rows_from_message(sent_msg)
        if allow_expand:
            for row in rows:
                for comp in row:
                    if comp.custom_id and comp.custom_id.startswith(EXPAND_ISSUE_CUSTOM_ID_PREFIX):
                        # get the current state if its already expanded
                        is_expanded = self.get_current_button_expansion_state(comp.custom_id)
                        row.remove_item(comp)
                        button = self.get_expand_button(links, is_expanded=is_expanded, user_id=after.author.id)
                        if button:
                            row.append_item(button)

        embed, *_ = self.format_embed(links, expand_one_issue=is_expanded)
        try:
            await sent_msg.edit(embed=embed, components=rows)
        except disnake.HTTPException:
            del self.autolink_cache[after.id]
            return

        # update the cache time
        self.autolink_cache.set(after.id, (sent_msg, after_issues))

    @commands.Cog.listener("on_message_delete")
    async def on_message_delete(self, message: disnake.Message) -> None:
        """Clear the message from the cache."""
        # TODO: refactor the cache to prune itself *somehow*
        try:
            del self.autolink_cache[message.id]
        except KeyError:
            pass

    @commands.slash_command()
    async def github(self, inter: disnake.ApplicationCommandInteraction, arg: str) -> None:
        """
        View information about an issue, pull, discussion, or comment on GitHub.

        Parameters
        ----------
        arg: Can be a org/repo#number, a link to an issue or issue comment, and more.
        """
        await self.on_message_automatic_issue_link(inter, content=arg)
        if not inter.response.is_done():
            msg = (
                f"{arg} could not be converted to a user, repo, combination, or link to a comment, pull, issue, or"
                " other type"
            )
            raise commands.BadArgument(msg)


def setup(bot: Monty) -> None:
    """Load the GithubInfo cog."""
    bot.add_cog(GithubInfo(bot))
