from .cog import GithubInfo


TYPE_CHECKING = 0

if TYPE_CHECKING:
    from monty.bot import Monty


def setup(bot: "Monty") -> None:
    """Setup the Github Info cog."""
    bot.add_cog(GithubInfo(bot))
