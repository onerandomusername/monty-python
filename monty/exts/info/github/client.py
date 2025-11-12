import base64

import ghretos
import githubkit
import githubkit.exception
import githubkit.rest
import msgpack

from . import graphql_models


DISCUSSION_COMMENT_GRAPHQL_QUERY = """
    query getDiscussionComment($id: ID!) {
        node(id: $id) {
            ... on DiscussionComment {
                id
                html_url: url
                body
                created_at: createdAt
                user: author {
                    __typename
                    login
                    html_url: url
                    avatar_url: avatarUrl
                }
            }
        }
    }
"""


class GitHubFetcher:
    """Wrapper methods around githubkit to fetch GitHub resources.

    This allows for reimplementing fetching logic in one place, such as using GraphQL.
    """

    def __init__(self, client: githubkit.GitHub) -> None:
        self.client = client
        self.headers = {
            "Accept": "application/vnd.github.full+json",
        }

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

    async def fetch_user(self, *, username: str) -> githubkit.rest.PublicUser:
        """Fetch a GitHub user by username."""
        r = await self.client.rest.users.async_get_by_username(username=username)
        data = r.parsed_data
        # Even though we use a token with no additional scopes, validate that we CERTAINLY only have public data.
        if data.user_view_type != "public" or not isinstance(data, githubkit.rest.PublicUser):
            msg = "User is not public"
            raise ValueError(msg)
        return data

    async def fetch_repo(self, *, owner: str, repo: str) -> githubkit.rest.FullRepository:
        """Fetch a GitHub repository by owner and name."""
        r = await self.client.rest.repos.async_get(owner=owner, repo=repo)
        return r.parsed_data

    async def fetch_issue(self, *, owner: str, repo: str, issue_number: int) -> githubkit.rest.Issue:
        """Fetch a GitHub issue by owner, name, and issue number."""
        r = await self.client.rest.issues.async_get(
            owner=owner,
            repo=repo,
            issue_number=issue_number,
        )
        return r.parsed_data

    async def fetch_pull_request(self, *, owner: str, repo: str, issue_number: int) -> githubkit.rest.Issue:
        """Fetch a GitHub issue by owner, name, and issue number."""
        r = await self.client.rest.issues.async_get(
            owner=owner,
            repo=repo,
            issue_number=issue_number,
        )
        return r.parsed_data

    async def fetch_discussion(self, *, owner: str, repo: str, discussion_number: int) -> githubkit.rest.Discussion:
        """Fetch a GitHub discussion by owner, name, and discussion number."""
        url = f"/repos/{owner}/{repo}/discussions/{discussion_number}"
        r = await self.client.arequest(
            "GET",
            url,
            headers={"X-GitHub-Api-Version": self.client.rest.meta._REST_API_VERSION},
            response_model=githubkit.rest.Discussion,
        )
        return r.parsed_data

    async def fetch_repo_numberable(
        self, *, owner: str, repo: str, number: int
    ) -> githubkit.rest.Issue | githubkit.rest.Discussion:
        """Fetch a GitHub issue or discussion by owner, name, and number."""
        try:
            return await self.fetch_issue(owner=owner, repo=repo, issue_number=number)
        except githubkit.exception.RequestFailed as e:
            if e.response.status_code != 404:
                raise
        return await self.fetch_discussion(owner=owner, repo=repo, discussion_number=number)

    async def fetch_issue_comment(self, *, owner: str, repo: str, comment_id: int) -> githubkit.rest.IssueComment:
        """Fetch a GitHub issue comment by owner, name, and comment ID."""
        r = await self.client.rest.issues.async_get_comment(
            owner=owner,
            repo=repo,
            comment_id=comment_id,
        )
        return r.parsed_data

    async def fetch_pull_request_comment(
        self, *, owner: str, repo: str, comment_id: int
    ) -> githubkit.rest.IssueComment:
        """Fetch a GitHub pull request comment by owner, name, and comment ID."""
        r = await self.client.rest.issues.async_get_comment(
            owner=owner,
            repo=repo,
            comment_id=comment_id,
        )
        return r.parsed_data

    async def fetch_pull_request_review_comment(
        self, *, owner: str, repo: str, comment_id: int
    ) -> githubkit.rest.PullRequestReviewComment:
        """Fetch a GitHub pull request review comment by owner, name, and comment ID."""
        r = await self.client.rest.pulls.async_get_review_comment(
            owner=owner,
            repo=repo,
            comment_id=comment_id,
        )
        return r.parsed_data

    async def fetch_discussion_comment(self, *, comment_id: int) -> graphql_models.DiscussionComment:
        """Fetch a GitHub discussion comment by comment ID."""
        r = await self.client.graphql.arequest(
            DISCUSSION_COMMENT_GRAPHQL_QUERY,
            variables={"id": self._format_github_global_id("DC", 0, comment_id)},
        )
        # Move `__typename` to `type` to fit the models
        r["node"]["user"]["type"] = r["node"]["user"].pop("__typename")
        return graphql_models.DiscussionComment(**r["node"])

    async def fetch_issue_event(self, *, owner: str, repo: str, event_id: int) -> githubkit.rest.IssueEvent:
        """Fetch a GitHub issue event by owner, name, and event ID."""
        r = await self.client.rest.issues.async_get_event(
            owner=owner,
            repo=repo,
            event_id=event_id,
        )
        return r.parsed_data

    async def fetch_pull_request_event(self, *, owner: str, repo: str, event_id: int) -> githubkit.rest.IssueEvent:
        """Fetch a GitHub pull request event by owner, name, and event ID."""
        r = await self.client.rest.issues.async_get_event(
            owner=owner,
            repo=repo,
            event_id=event_id,
        )
        return r.parsed_data

    async def fetch_commit(self, *, owner: str, repo: str, sha: str) -> githubkit.rest.Commit:
        """Fetch a GitHub commit by owner, name, and SHA."""
        r = await self.client.rest.repos.async_get_commit(
            owner=owner,
            repo=repo,
            ref=sha,
        )
        return r.parsed_data

    # TODO: remove this method
    async def fetch_resource(self, obj: ghretos.GitHubResource) -> githubkit.GitHubModel:
        """Fetch a GitHub object by its type and identifiers.

        This method is a convenience wrapper around the other fetch methods in this class.
        """
        match obj:
            case ghretos.User():
                return await self.fetch_user(username=obj.login)
            case ghretos.Repo():
                return await self.fetch_repo(owner=obj.owner, repo=obj.name)
            case ghretos.NumberedResource():
                return await self.fetch_repo_numberable(owner=obj.repo.owner, repo=obj.repo.name, number=obj.number)
            case ghretos.Issue():
                return await self.fetch_issue(owner=obj.repo.owner, repo=obj.repo.name, issue_number=obj.number)
            case ghretos.PullRequest():
                return await self.fetch_pull_request(owner=obj.repo.owner, repo=obj.repo.name, issue_number=obj.number)
            case ghretos.Discussion():
                return await self.fetch_discussion(
                    owner=obj.repo.owner, repo=obj.repo.owner, discussion_number=obj.number
                )
            case ghretos.IssueComment():
                return await self.fetch_issue_comment(
                    owner=obj.repo.owner, repo=obj.repo.name, comment_id=obj.comment_id
                )
            case ghretos.PullRequestComment():
                return await self.fetch_pull_request_comment(
                    owner=obj.repo.owner, repo=obj.repo.name, comment_id=obj.comment_id
                )
            case ghretos.PullRequestReviewComment():
                return await self.fetch_pull_request_review_comment(
                    owner=obj.repo.owner, repo=obj.repo.name, comment_id=obj.comment_id
                )
            case ghretos.DiscussionComment():
                return await self.fetch_discussion_comment(comment_id=obj.comment_id)
            case ghretos.IssueEvent():
                return await self.fetch_issue_event(owner=obj.repo.owner, repo=obj.repo.name, event_id=obj.event_id)
            case ghretos.PullRequestEvent():
                return await self.fetch_pull_request_event(
                    owner=obj.repo.owner, repo=obj.repo.name, event_id=obj.event_id
                )
            case ghretos.Commit():
                return await self.fetch_commit(owner=obj.repo.owner, repo=obj.repo.name, sha=obj.sha)
        msg = f"Fetching for resource type {type(obj)} is not implemented"
        raise NotImplementedError(msg)
