from monty.bot import Bot


def setup(bot: Bot) -> None:
    """Load the CodeBlockCog cog."""
    # Defer import to reduce side effects from importing the codeblock package.
    from monty.exts.info.codeblock._cog import CodeBlockCog

    bot.add_cog(CodeBlockCog(bot))
