from dataclasses import dataclass


@dataclass()
class ExtMetadata:
    """Ext metadata class to determine if extension should load at runtime depending on bot configuration."""

    core: bool = False
    "Whether or not to always load by default."
    no_unload: bool = False
    "False to allow the cog to be unloaded, True to block."
    has_cog: bool = True
    "Whether or not the extension has a cog to check for load status."

    def __init__(
        self,
        *,
        core: bool = False,
        no_unload: bool = False,
        has_cog: bool = True,
    ) -> None:
        self.core = core
        self.no_unload = no_unload
        self.has_cog = has_cog
