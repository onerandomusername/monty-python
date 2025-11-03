import logging
import pathlib

from wand.color import Color
from wand.image import Image

from monty.constants import GITHUB_OCTICONS, Client, GHColour


DIRECTORY = pathlib.Path(Client.app_emoji_directory.lstrip("\\/"))

log = logging.getLogger(__name__)


def convert_svg_to_png(data: bytes, colour: GHColour) -> bytes:
    """Convert SVG data to PNG format with the specified colour."""
    with Image(
        blob=data,
        format="svg",
        height=128,
        width=128,
        background=Color("transparent"),
    ) as img:
        img.opaque_paint(
            target=Color("black"),
            fill=Color(f"#{colour.value:06X}"),
            fuzz=img.quantum_range * 0.05,
        )
        img.format = "apng"
        img.strip()
        return img.make_blob()


def fetch_octicons() -> dict[str, bytes]:
    """Fetch the octicons from GitHub and convert them to PNG format."""
    octicons_data: dict[str, bytes] = {}
    for octicon in GITHUB_OCTICONS:
        png_data = convert_svg_to_png(octicon.icon().svg.encode(), octicon.color)
        octicons_data[octicon.name] = png_data
        log.info("Fetched and converted octicon %s as %s", octicon.slug, octicon.name)
    return octicons_data


if __name__ == "__main__":
    octicons = fetch_octicons()
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    for name, data in octicons.items():
        _ = (DIRECTORY / f"{name.replace('-', '_')}.png").write_bytes(data)
