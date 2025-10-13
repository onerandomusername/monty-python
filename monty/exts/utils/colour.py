import colorsys
import json
import pathlib
import random
import string
from io import BytesIO

import disnake
import rapidfuzz
from disnake.ext import commands
from PIL import Image, ImageColor

from monty.bot import Monty
from monty.errors import MontyCommandError
from monty.utils.extensions import invoke_help_command
from monty.utils.messages import DeleteButton


THUMBNAIL_SIZE = (80, 80)


class Colour(
    commands.Cog,
    slash_command_attrs={
        "contexts": disnake.InteractionContextTypes.all(),
        "install_types": disnake.ApplicationInstallTypes.all(),
    },
):
    """Cog for the Colour command."""

    def __init__(self, bot: Monty) -> None:
        self.bot = bot
        with open(pathlib.Path("monty/resources/ryanzec_colours.json")) as f:
            self.colour_mapping = json.load(f)
            del self.colour_mapping["_"]  # Delete source credit entry

    async def send_colour_response(
        self,
        ctx: commands.Context | disnake.ApplicationCommandInteraction,
        rgb: tuple[int, int, int],
        input_colour: str | None,
    ) -> None:
        """Create and send embed from user given colour information."""
        name = self._rgb_to_name(rgb) or ""
        if isinstance(ctx, commands.Context):
            if ctx.invoked_parents:
                colour_or_color = ctx.invoked_parents[0]
            else:
                colour_or_color = "colour"
            colour_mode = ctx.invoked_with or ""
            kwargs = ctx.kwargs
        elif isinstance(ctx, disnake.Interaction):
            colour_or_color = "color" if ctx.locale is disnake.Locale.en_US else "colour"

            colour_mode = ctx.application_command.name
            kwargs = ctx.filled_options

        if colour_mode == "random":
            colour_mode = colour_or_color
            input_colour = name
        elif colour_mode in ("colour", "color"):
            input_colour = kwargs["colour_input"]
        elif colour_mode == "name":
            input_colour = kwargs["name"]
        elif colour_mode == "hex":
            if input_colour and len(input_colour) > 7:
                input_colour = input_colour[:-2]
        else:
            input_colour = str(rgb)

        if colour_mode in ("name", "hex", "random", "color", "colour"):
            colour_mode = colour_mode.title()
        else:
            colour_mode = colour_mode.upper()

        colour_embed = disnake.Embed(
            title=f"{name or input_colour}",
            colour=disnake.Color.from_rgb(*rgb),
        )
        description = f"{colour_or_color.title()} information "
        if input_colour or name:
            description += f"for {colour_mode} `{input_colour or name}`"
        else:
            description += f"for RGB `{rgb[0]}, {rgb[1]}, {rgb[2]}`"
        colour_embed.description = description

        colour_conversions = self.get_colour_conversions(rgb)
        for colour_space, value in colour_conversions.items():
            colour_embed.add_field(name=colour_space, value=f"`{value}`", inline=True)

        thumbnail = Image.new("RGB", THUMBNAIL_SIZE, color=rgb)
        buffer = BytesIO()
        thumbnail.save(buffer, "PNG")
        buffer.seek(0)
        thumbnail_file = disnake.File(buffer, filename="colour.png")

        colour_embed.set_thumbnail(url="attachment://colour.png")

        if isinstance(ctx, commands.Context):
            components = DeleteButton(ctx.author, initial_message=ctx.message)
        else:
            components = DeleteButton(ctx.author)
        await ctx.send(file=thumbnail_file, embed=colour_embed, components=components)

    @commands.group(aliases=("color",), invoke_without_command=True)
    async def colour(self, ctx: commands.Context, *, colour_input: str | None = None) -> None:
        """
        Create an embed that displays colour information.

        If no subcommand is called, a randomly selected colour will be shown.
        """
        if colour_input is None:
            await self.random(ctx)
            return

        try:
            extra_colour = ImageColor.getrgb(colour_input)[:3]
            await self.send_colour_response(ctx, extra_colour, input_colour=colour_input)
        except ValueError:
            await invoke_help_command(ctx)

    @commands.slash_command(name=disnake.Localised("colour", data={disnake.Locale.en_US: "color"}))
    async def slash_colour(self, inter: disnake.ApplicationCommandInteraction) -> None:
        """Show information about a colour."""

    @colour.command()
    async def rgb(self, ctx: commands.Context, red: int, green: int, blue: int) -> None:
        """Create an embed from an RGB input."""
        if any(c not in range(256) for c in (red, green, blue)):
            raise commands.BadArgument(
                message=f"RGB values can only be from 0 to 255. User input was: `{red, green, blue}`."
            )
        rgb_tuple = (red, green, blue)
        await self.send_colour_response(ctx, rgb_tuple, input_colour=f"{red}, {green}, {blue}")

    @slash_colour.sub_command(name="rgb")
    async def slash_rgb(
        self,
        inter: disnake.ApplicationCommandInteraction,
        red: commands.Range[int, 0, 255],
        green: commands.Range[int, 0, 255],
        blue: commands.Range[int, 0, 255],
    ) -> None:
        """
        RGB Format.

        Parameters
        ----------
        red: Red.
        green: Green.
        blue: Blue.
        """
        rgb_tuple = (red, green, blue)
        await self.send_colour_response(inter, rgb_tuple, input_colour=f"{red}, {green}, {blue}")

    @colour.command()
    async def hsv(self, ctx: commands.Context, hue: int, saturation: int, value: int) -> None:
        """Create an embed from an HSV input."""
        if (hue not in range(361)) or any(c not in range(101) for c in (saturation, value)):
            raise commands.BadArgument(
                message=(
                    "Hue can only be from 0 to 360. Saturation and Value can only be from 0 to 100. "
                    f"User input was: `{hue, saturation, value}`."
                )
            )
        input_colour = f"hsv({hue}, {saturation}%, {value}%)"
        hsv_tuple = ImageColor.getrgb(input_colour)[:3]
        await self.send_colour_response(ctx, hsv_tuple, input_colour=input_colour)

    @slash_colour.sub_command(name="hsv")
    async def slash_hsv(
        self,
        inter: disnake.ApplicationCommandInteraction,
        hue: commands.Range[int, 0, 360],
        sat: commands.Range[int, 0, 360],
        value: commands.Range[int, 0, 100],
    ) -> None:
        """
        HSV Format.

        Parameters
        ----------
        hue: Hue.
        sat: Saturation.
        value: Value.
        """
        input_colour = f"hsv({hue}, {sat}%, {value}%)"
        hsv_tuple = ImageColor.getrgb(input_colour)[:3]
        await self.send_colour_response(inter, hsv_tuple, input_colour=input_colour)

    @colour.command()
    async def hsl(self, ctx: commands.Context, hue: int, saturation: int, lightness: int) -> None:
        """Create an embed from an HSL input."""
        if (hue not in range(361)) or any(c not in range(101) for c in (saturation, lightness)):
            raise commands.BadArgument(
                message=(
                    "Hue can only be from 0 to 360. Saturation and Lightness can only be from 0 to 100. "
                    f"User input was: `{hue, saturation, lightness}`."
                )
            )
        input_colour = f"hsl({hue}, {saturation}%, {lightness}%)"
        hsl_tuple = ImageColor.getrgb(input_colour)[:3]
        await self.send_colour_response(ctx, hsl_tuple, input_colour=input_colour)

    @slash_colour.sub_command(name="hsl")
    async def slash_hsl(
        self,
        inter: disnake.ApplicationCommandInteraction,
        hue: commands.Range[int, 0, 360],
        sat: commands.Range[int, 0, 360],
        lightness: commands.Range[int, 0, 100],
    ) -> None:
        """
        HSL Format.

        Parameters
        ----------
        hue: Hue.
        sat: Saturation.
        lightness: Lightness.
        """
        input_colour = f"hsl({hue}, {sat}%, {lightness}%)"
        hsl_tuple = ImageColor.getrgb(input_colour)[:3]
        await self.send_colour_response(inter, hsl_tuple, input_colour=input_colour)

    @colour.command()
    async def cmyk(self, ctx: commands.Context, cyan: int, magenta: int, yellow: int, black: int) -> None:
        """Create an embed from a CMYK input."""
        if any(c not in range(101) for c in (cyan, magenta, yellow, black)):
            raise commands.BadArgument(
                message=f"CMYK values can only be from 0 to 100. User input was: `{cyan, magenta, yellow, black}`."
            )
        r = round(255 * (1 - (cyan / 100)) * (1 - (black / 100)))
        g = round(255 * (1 - (magenta / 100)) * (1 - (black / 100)))
        b = round(255 * (1 - (yellow / 100)) * (1 - (black / 100)))
        await self.send_colour_response(ctx, (r, g, b), input_colour=f"CMYK: {cyan}, {magenta}, {yellow}, {black}")

    # TODO: fix this typoed name
    @slash_colour.sub_command(name="cymk")
    async def slash_cmyk(
        self,
        inter: disnake.ApplicationCommandInteraction,
        cyan: commands.Range[int, 0, 100],
        magenta: commands.Range[int, 0, 100],
        yellow: commands.Range[int, 0, 100],
        black: commands.Range[int, 0, 100],
    ) -> None:
        """
        CMYK Format.

        Parameters
        ----------
        cyan: Cyan.
        magenta: Magenta.
        yellow: Yellow.
        black: Black.
        """
        if any(c not in range(101) for c in (cyan, magenta, yellow, black)):
            raise commands.BadArgument(
                message=f"CMYK values can only be from 0 to 100. User input was: `{cyan, magenta, yellow, black}`."
            )
        r = round(255 * (1 - (cyan / 100)) * (1 - (black / 100)))
        g = round(255 * (1 - (magenta / 100)) * (1 - (black / 100)))
        b = round(255 * (1 - (yellow / 100)) * (1 - (black / 100)))
        await self.send_colour_response(inter, (r, g, b), input_colour=f"CMYK: {cyan}, {magenta}, {yellow}, {black}")

    def _hex(self, hex_code: str) -> tuple[str, tuple[int, int, int]]:
        """Convert HEX code to RGB tuple."""
        if hex_code[0] != "#":
            hex_code = f"#{hex_code}"
        if len(hex_code) not in (4, 5, 7, 9) or any(digit not in string.hexdigits for digit in hex_code[1:]):
            raise commands.BadArgument(
                message=(
                    f"Cannot convert `{hex_code}` to a recognizable Hex format. "
                    "Hex values must be hexadecimal and take the form *#RRGGBB* or *#RGB*."
                )
            )
        return hex_code, ImageColor.getrgb(hex_code)[:3]

    @colour.command()
    async def hex(self, ctx: commands.Context | disnake.ApplicationCommandInteraction, hex_code: str) -> None:
        """Create an embed from a HEX input."""
        hex_code, hex_tuple = self._hex(hex_code)
        await self.send_colour_response(ctx, hex_tuple, input_colour=hex_code)

    @slash_colour.sub_command(name="hex")
    async def slash_hex(self, inter: disnake.ApplicationCommandInteraction, hex: str) -> None:
        """
        HEX Format.

        Parameters
        ----------
        hex: Hex colour code.
        """
        hex, hex_tuple = self._hex(hex)
        await self.send_colour_response(inter, hex_tuple, input_colour=hex)

    def _name(self, name: str) -> tuple[str, tuple[int, int, int]]:
        """Convert colour name to RGB tuple."""
        matched_hex = self.match_colour_name(name)
        if matched_hex is None:
            msg = f"Could not find a close match for the colour name `{name}`."
            raise MontyCommandError(msg)
        return name, ImageColor.getrgb(matched_hex)[:3]

    @colour.command()
    async def name(self, ctx: commands.Context, *, name: str) -> None:
        """Create an embed from a name input."""
        name, name_tuple = self._name(name)
        await self.send_colour_response(ctx, name_tuple, input_colour=name)

    @slash_colour.sub_command(name="name")
    async def slash_name(self, inter: disnake.ApplicationCommandInteraction, name: str) -> None:
        """
        Get a colour by name.

        Parameters
        ----------
        name: Colour name, by close match.
        """
        name, name_tuple = self._name(name)
        await self.send_colour_response(inter, name_tuple, input_colour=name)

    def _random(self) -> tuple[int, int, int]:
        """Generate a random RGB tuple."""
        hex_colour = random.choice(list(self.colour_mapping.values()))
        hex_tuple = ImageColor.getrgb(f"#{hex_colour}")
        if len(hex_tuple) > 3:
            hex_tuple = hex_tuple[:3]
        return (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))

    @colour.command()
    async def random(self, ctx: commands.Context) -> None:
        """Create an embed from a randomly chosen colour."""
        await self.send_colour_response(ctx, self._random(), input_colour=None)

    @slash_colour.sub_command(name="random")
    async def slash_random(self, inter: disnake.ApplicationCommandInteraction) -> None:
        """Random colour."""
        await self.send_colour_response(inter, self._random(), input_colour=None)

    def get_colour_conversions(
        self, rgb: tuple[int, int, int]
    ) -> dict[str, tuple[int, int, int] | tuple[int, int, int, int] | str]:
        """Create a dictionary mapping of colour types and their values."""
        colour_name = self._rgb_to_name(rgb)
        if colour_name is None:
            colour_name = "No match found"
        return {
            "RGB": rgb,
            "HSV": self._rgb_to_hsv(rgb),
            "HSL": self._rgb_to_hsl(rgb),
            "CMYK": self._rgb_to_cmyk(rgb),
            "Hex": self._rgb_to_hex(rgb),
            "Name": colour_name,
        }

    @staticmethod
    def _rgb_to_hsv(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
        """Convert RGB values to HSV values."""
        rgb_list = [val / 255 for val in rgb]
        h, s, v = colorsys.rgb_to_hsv(*rgb_list)
        hsv = (round(h * 360), round(s * 100), round(v * 100))
        return hsv

    @staticmethod
    def _rgb_to_hsl(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
        """Convert RGB values to HSL values."""
        rgb_list = [val / 255.0 for val in rgb]
        h, l, s = colorsys.rgb_to_hls(*rgb_list)  # noqa: E741
        hsl = (round(h * 360), round(s * 100), round(l * 100))
        return hsl

    @staticmethod
    def _rgb_to_cmyk(rgb: tuple[int, int, int]) -> tuple[int, int, int, int]:
        """Convert RGB values to CMYK values."""
        rgb_list = [val / 255.0 for val in rgb]
        if not any(rgb_list):
            return 0, 0, 0, 100
        k = 1 - max(rgb_list)
        c = round((1 - rgb_list[0] - k) * 100 / (1 - k))
        m = round((1 - rgb_list[1] - k) * 100 / (1 - k))
        y = round((1 - rgb_list[2] - k) * 100 / (1 - k))
        cmyk = (c, m, y, round(k * 100))
        return cmyk

    @staticmethod
    def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
        """Convert RGB values to HEX code."""
        hex_ = "".join([hex(val)[2:].zfill(2) for val in rgb])
        hex_code = f"#{hex_}".upper()
        return hex_code

    def _rgb_to_name(self, rgb: tuple[int, int, int]) -> str | None:
        """Convert RGB values to a fuzzy matched name."""
        input_hex_colour = self._rgb_to_hex(rgb)
        try:
            result = rapidfuzz.process.extractOne(
                query=input_hex_colour, choices=self.colour_mapping.values(), score_cutoff=80
            )
            if result:
                match, certainty, _ = result
                return [name for name, hex_code in self.colour_mapping.items() if hex_code == match][0]
        except (TypeError, ValueError):
            pass
        return None

    def match_colour_name(self, input_colour_name: str) -> str | None:
        """Convert a colour name to HEX code."""
        try:
            result = rapidfuzz.process.extractOne(
                query=input_colour_name, choices=self.colour_mapping.keys(), score_cutoff=80
            )
            if result:
                match, certainty, _ = result
                return f"#{self.colour_mapping[match]}"
        except (ValueError, TypeError):
            pass
        return None


def setup(bot: Monty) -> None:
    """Load the Colour cog."""
    bot.add_cog(Colour(bot))
