import cachingutils.redis

from monty import constants
from monty.bot import Monty

from ._redis_cache import DocRedisCache


MAX_SIGNATURE_AMOUNT = 3
PRIORITY_PACKAGES = ("python",)
NAMESPACE = "doc"

_cache = cachingutils.redis.async_session(constants.Client.config_prefix)
doc_cache = DocRedisCache(prefix=_cache._prefix + "docs", session=_cache._redis)


def setup(bot: Monty) -> None:
    """Load the Doc cog."""
    from ._cog import DocCog

    bot.add_cog(DocCog(bot))
