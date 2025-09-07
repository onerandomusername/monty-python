import typing
from typing import Dict, Optional

from aiohttp import ClientConnectorError
from attrs import define

from monty import constants
from monty.bot import Monty
from monty.errors import APIError
from monty.log import get_logger


if typing.TYPE_CHECKING:
    import aiohttp

log = get_logger(__name__)

FAILED_REQUEST_ATTEMPTS = 3

PASTE_DISABLED = not constants.URLs.paste_service

GITHUB_REQUEST_HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
if constants.Tokens.github:
    GITHUB_REQUEST_HEADERS["Authorization"] = f"token {constants.Tokens.github}"


@define()
class GitHubRateLimit:
    limit: int
    remaining: int
    reset: int
    used: int


GITHUB_RATELIMITS: dict[str, GitHubRateLimit] = {}


async def send_to_paste_service(bot: Monty, contents: str, *, extension: str = "") -> Optional[str]:
    """
    Upload `contents` to the paste service.

    `extension` is added to the output URL

    When an error occurs, `None` is returned, otherwise the generated URL with the suffix.
    """
    if PASTE_DISABLED:
        return "Sorry, paste isn't configured!"

    log.debug(f"Sending contents of size {len(contents.encode())} bytes to paste service.")
    paste_url = constants.URLs.paste_service.format(key="api/new")
    json: dict[str, str] = {
        "content": contents,
    }
    if extension:
        json["language"] = extension
    response = None
    for attempt in range(1, FAILED_REQUEST_ATTEMPTS + 1):
        response_json = {}
        try:
            async with bot.http_session.post(paste_url, json=json) as response:
                response_json = await response.json()
                if not 200 <= response.status < 300 and attempt == FAILED_REQUEST_ATTEMPTS:
                    raise APIError("workbin", response.status, "The paste service could not be used at this time.")
        except ClientConnectorError:
            log.warning(
                f"Failed to connect to paste service at url {paste_url}, "
                f"trying again ({attempt}/{FAILED_REQUEST_ATTEMPTS})."
            )
            continue
        except Exception:
            log.exception(
                "An unexpected error has occurred during handling of the request, "
                f"trying again ({attempt}/{FAILED_REQUEST_ATTEMPTS})."
            )
            continue

        if "message" in response_json:
            log.warning(
                f"Paste service returned error {response_json['message']} with status code {response.status}, "
                f"trying again ({attempt}/{FAILED_REQUEST_ATTEMPTS})."
            )
            continue
        elif "key" in response_json:
            log.info(f"Successfully uploaded contents to paste service behind key {response_json['key']}.")

            paste_link = constants.URLs.paste_service.format(key=f"?id={response_json['key']}")
            if extension:
                paste_link += f"&language={extension}"

            return paste_link

        log.warning(
            f"Got unexpected JSON response from paste service: {response_json}\n"
            f"trying again ({attempt}/{FAILED_REQUEST_ATTEMPTS})."
        )

    raise APIError("workbin", response.status if response else 0, "The paste service could not be used at this time.")


# https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api?apiVersion=2022-11-28#checking-the-status-of-your-rate-limit
def update_github_ratelimits_on_request(resp: "aiohttp.ClientResponse") -> None:
    """Given a ClientResponse, update the stored GitHub Ratelimits."""
    resource_name = resp.headers.get("x-ratelimit-resource")
    if not resource_name:
        # there's nothing to update as the resource name does not exist
        return
    GITHUB_RATELIMITS[resource_name] = GitHubRateLimit(
        limit=int(resp.headers["x-ratelimit-limit"]),
        remaining=int(resp.headers["x-ratelimit-remaining"]),
        reset=int(resp.headers["x-ratelimit-reset"]),
        used=int(resp.headers["x-ratelimit-used"]),
    )


# https://docs.github.com/en/rest/rate-limit/rate-limit?apiVersion=2022-11-28
def update_github_ratelimits_from_ratelimit_page(json: dict[str, typing.Any]) -> None:
    """Given the response from GitHub's rate_limit API page, update the stored GitHub Ratelimits."""
    ratelimits: Dict[str, Dict[str, int]] = json["resources"]
    for name, resource in ratelimits.items():
        GITHUB_RATELIMITS[name] = GitHubRateLimit(
            limit=resource["limit"],
            remaining=resource["remaining"],
            reset=resource["reset"],
            used=resource["used"],
        )
