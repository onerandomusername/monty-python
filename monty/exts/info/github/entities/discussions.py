from githubkit import GitHub, TokenAuthStrategy
from githubkit.exception import GraphQLFailed

from monty.exts.info.github.models import Discussion


DISCUSSION_QUERY = """
query getDiscussion($number: Int!, $org: String!, $repo: String!) {
  repository(owner: $org, name: $repo) {
    discussion(number: $number) {
      body
      title
      number
      user: author {
        login
        html_url: url
        avatar_url: avatarUrl
      }
      created_at: createdAt
      html_url: url
      state_reason: stateReason
      closed
      answer {
        user: author {
          login
          html_url: url
          avatar_url: avatarUrl
        }
      }
    }
  }
}
"""


async def get_discussion(gh: GitHub[TokenAuthStrategy], org: str, name: str, number: int) -> Discussion | None:
    try:
        resp = await gh.graphql.arequest(DISCUSSION_QUERY, variables={"number": number, "org": org, "repo": name})
    except GraphQLFailed:
        return None
    data = resp["repository"]["discussion"]
    data["answered_by"] = (answer := data.pop("answer")) and answer["user"]
    return Discussion(**data)
