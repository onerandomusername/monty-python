import pathlib

import httpx
from wand.color import Color
from wand.image import Image

from monty.constants import GITHUB_OCTICONS, Client, GHColour


DIRECTORY = pathlib.Path(Client.app_emoji_directory)


def convert_svg_to_png(data: bytes, colour: GHColour) -> bytes:
    """Convert SVG data to PNG format with the specified colour."""
    with Image(
        blob=data,
        format="svg",
        height=256,
        width=256,
        resolution=512,
        background=Color("transparent"),
    ) as img:
        img.format = "png"
        img_colour = Color(f"#{colour.value:06X}")
        img.opaque_paint(
            target=Color("black"),
            fill=img_colour,
            fuzz=img.quantum_range * 0.05,
        )
        return img.make_blob()


def fetch_octicons() -> dict[str, bytes]:
    """Fetch the octicons from GitHub and convert them to PNG format."""
    octicons_data: dict[str, bytes] = {}
    with httpx.Client(follow_redirects=True) as client:
        for octicon in GITHUB_OCTICONS:
            response = client.get(octicon.url())
            response.raise_for_status()
            png_data = convert_svg_to_png(response.content, octicon.color)
            octicons_data[octicon.name] = png_data
    return octicons_data


if __name__ == "__main__":
    octicons = fetch_octicons()
    for name, data in octicons.items():
        _ = (DIRECTORY / f"{name.replace('-', '_')}.png").write_bytes(data)
