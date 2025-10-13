import re

import aiohttp
import disnake
import yarl
from disnake.ext import commands


AnyContext = disnake.ApplicationCommandInteraction | commands.Context
GITHUB_ORG_REGEX = re.compile(r"[a-zA-Z0-9\-]{1,}")


async def validate_github_org(ctx: AnyContext, arg: str) -> bool:
    """Validate all GitHub orgs meet GitHub's naming requirements."""
    if not arg:
        return True  # optional support
    if not GITHUB_ORG_REGEX.fullmatch(arg):
        err = f"The GitHub org '{arg}' is not a valid GitHub organisation name."
        raise ValueError(err)

    url = yarl.URL("https://github.com").with_path(arg)
    # TODO: use the API rather than a HEAD request: eg /sponsors is not a user
    try:
        r = await ctx.bot.http_session.head(url, raise_for_status=True)
    except aiohttp.ClientResponseError:
        msg = (
            "Organisation must be a valid GitHub user or organisation. Please check the provided account exists on"
            " GitHub and try again."
        )
        raise commands.UserInputError(msg) from None
    else:
        r.close()
    return True
