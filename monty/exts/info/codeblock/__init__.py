from monty.bot import Monty


def setup(bot: Monty) -> None:
    """Load the CodeBlockCog cog."""
    # Defer import to reduce side effects from importing the codeblock package.
    from monty.exts.info.codeblock._cog import CodeBlockCog

    bot.add_cog(CodeBlockCog(bot))
