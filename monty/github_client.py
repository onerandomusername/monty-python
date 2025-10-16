from typing import Any

from githubkit import GitHub


class GitHubClient(GitHub):
    def __init__(self, *args, **kwargs):
        self._transport = kwargs.pop("transport", None)
        kwargs["http_cache"] = False
        super().__init__(*args, **kwargs)

    def _get_client_defaults(self) -> dict[str, Any]:
        defaults = super()._get_client_defaults()
        if self._transport is not None:
            defaults["transport"] = self._transport
        return defaults
