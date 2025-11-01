import datetime

import githubkit


class DiscussionCommentUser(githubkit.GitHubModel):
    """Response model for user discussion comments."""

    login: str
    html_url: str
    avatar_url: str
    name: None = None


class DiscussionComment(githubkit.GitHubModel):
    """Response model for a discussion comment."""

    id: str
    body: str
    created_at: datetime.datetime
    html_url: str
    user: DiscussionCommentUser
