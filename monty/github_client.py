from githubkit import GitHub


# This previously existed for overwriting async_transport, but now that exists in githubkit,
# this exists because adding a new custom feature is easy if desired.
class GitHubClient(GitHub):
    def __init__(self, *args, **kwargs):
        kwargs["http_cache"] = False
        super().__init__(*args, **kwargs)
