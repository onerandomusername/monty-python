import disnake
from disnake.ext import commands

from monty.bot import Monty


INVITE = """
**Created at**: {invite.created_at}
**Expires at**: {invite.expires_at}
**Max uses**: {invite.max_uses}
"""
INVITE_GUILD_INFO = """
**Name**: {guild.name}
**ID**: {guild.id}
**Approx. Member Count**: {invite.approximate_member_count}
**Approx. Online Members**: {invite.approximate_presence_count}
**Description**: {guild.description}
"""
INVITE_USER = """
**Usertag**: {inviter}
**ID**: {inviter.id}
"""


class Discord(commands.Cog):
    """Useful discord api commands."""

    def __init__(self, bot: Monty):
        self.bot = bot

    @commands.slash_command()
    async def discord(self, inter: disnake.CommandInteraction) -> None:
        """Commands that interact with discord."""
        pass

    @discord.sub_command_group()
    async def api(self, inter: disnake.CommandInteraction) -> None:
        """Commands that interact with the discord api."""
        pass

    @api.sub_command()
    async def guild_invite(
        self, inter: disnake.CommandInteraction, invite: disnake.Invite, ephemeral: bool = True
    ) -> None:
        """Get information on a guild from an invite."""
        if not invite.guild:
            await inter.send("Group dm invites are not supported.", ephemeral=True)
            return
        if invite.guild.nsfw_level not in (disnake.NSFWLevel.default, disnake.NSFWLevel.safe):
            await inter.send(f"Refusing to process invite for the nsfw guild, {invite.guild.name}.", ephemeral=True)
            return

        embed = disnake.Embed(title=f"Invite for {invite.guild.name}")
        if invite.created_at or invite.expires_at or invite.max_uses:
            embed.description = INVITE.format(invite=invite, guild=invite.guild)

        embed.add_field(name="Guild Info", value=INVITE_GUILD_INFO.format(invite=invite, guild=invite.guild))
        if invite.inviter:
            embed.add_field("Inviter Info:", INVITE_USER.format(inviter=invite.inviter), inline=False)

        embed.set_author(name=invite.guild.name)
        if image := (invite.guild.banner or invite.guild.splash):
            image = image.with_size(1024)
            embed.set_image(url=image.url)

        if invite.guild.icon is not None:
            embed.set_thumbnail(url=invite.guild.icon.url)

        await inter.send(embed=embed, ephemeral=ephemeral)

    @guild_invite.error
    async def guild_invite_error(self, inter: disnake.CommandInteraction, error: Exception) -> None:
        """Handle errors for guild_invite."""
        if isinstance(error, commands.ConversionError):
            error = error.original
        if isinstance(error, commands.BadInviteArgument):
            await inter.send(str(error), ephemeral=True)
            return


def setup(bot: Monty) -> None:
    """Load the Discord cog."""
    bot.add_cog(Discord(bot))
