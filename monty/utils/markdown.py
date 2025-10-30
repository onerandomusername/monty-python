import re
from typing import Any
from urllib.parse import urljoin

import mistune.renderers
from bs4.element import PageElement, Tag
from markdownify import MarkdownConverter

from monty import constants


__all__ = (
    "DiscordRenderer",
    "DocMarkdownConverter",
    "remove_codeblocks",
)


CODE_BLOCK_RE = re.compile(
    r"```(.+?)```|(?P<delim>`{1,2})([^\n]+?)(?P=delim)",
    re.DOTALL | re.MULTILINE,
)

# references should be preceded by a non-word character (or element start)
GH_ISSUE_RE = re.compile(r"(?:^|(?<=\W))(?:#|GH-)(\d+)\b", re.IGNORECASE)


def remove_codeblocks(content: str) -> str:
    """Remove any codeblock in a message."""
    return CODE_BLOCK_RE.sub("", content)


class DocMarkdownConverter(MarkdownConverter):
    """Subclass markdownify's MarkdownCoverter to provide custom conversion methods."""

    def __init__(self, *, page_url: str, **options):
        # Reflow text to avoid unwanted line breaks.
        default_options = {"wrap": True, "wrap_width": None}

        super().__init__(**default_options | options)
        self.page_url = page_url

    def convert_img(self, el: PageElement, text: str, parent_tags: set[str]) -> str:
        """Remove images from the parsed contents, we don't want them."""
        return ""

    def convert_li(self, el: Tag, text: str, parent_tags: set[str]) -> str:
        """Fix markdownify's erroneous indexing in ol tags."""
        parent = el.parent
        if parent is not None and parent.name == "ol":
            li_tags = parent.find_all("li")
            bullet = f"{li_tags.index(el) + 1}."
        else:
            depth = -1
            curr_el = el
            while curr_el:
                if curr_el.name == "ul":
                    depth += 1
                curr_el = curr_el.parent
            bullets = self.options["bullets"]
            bullet = bullets[depth % len(bullets)]
        return f"{bullet} {text}\n"

    def _convert_hn(self, n: int, el: PageElement, text: str, parent_tags: set[str]) -> str:
        """Convert h tags to bold text with ** instead of adding #."""
        if "_inline" in parent_tags:
            return text
        return f"**{text}**\n\n"

    def convert_code(self, el: PageElement, text: str, parent_tags: set[str]) -> str:
        """Undo `markdownify`s underscore escaping."""
        return f"`{text}`".replace("\\", "")

    def convert_pre(self, el: Tag, text: str, parent_tags: set[str]) -> str:  # pyright: ignore[reportIncompatibleMethodOverride] # bug in pyright
        """Wrap any codeblocks in `py` for syntax highlighting."""
        code = "".join(el.strings)
        return f"```py\n{code}```"

    def convert_a(self, el: Tag, text: str, parent_tags: set[str]) -> str:
        """Resolve relative URLs to `self.page_url`."""
        href = el["href"]
        assert isinstance(href, str)
        el["href"] = urljoin(self.page_url, href)
        # Discord doesn't handle titles properly, showing links with them as raw text.
        el["title"] = ""
        return super().convert_a(el, text, parent_tags)

    def convert_p(self, el: PageElement, text: str, parent_tags: set[str]) -> str:
        """Include only one newline instead of two when the parent is a li tag."""
        if "_inline" in parent_tags:
            return text

        parent = el.parent
        if parent is not None and parent.name == "li":
            return f"{text}\n"
        return super().convert_p(el, text, parent_tags)

    def convert_hr(self, el: PageElement, text: str, parent_tags: set[str]) -> str:  # pyright: ignore[reportIncompatibleMethodOverride] # bug in pyright
        """Ignore `hr` tag."""
        return ""


# TODO: this will be expanded over time as necessary
class DiscordRenderer(mistune.renderers.BaseRenderer):
    """Custom renderer for markdown to discord compatiable markdown."""

    def __init__(self, repo: str | None = None) -> None:
        self._repo = (repo or "").rstrip("/")

    def text(self, text: str) -> str:
        """Replace GitHub links with their expanded versions."""
        if self._repo:
            # TODO: expand this to all different varieties of automatic links
            # if a repository is provided we replace all snippets with the correct thing
            def replacement(match: re.Match[str]) -> str:
                return self.link(self._repo + "/issues/" + match[1], text=match[0])

            text = GH_ISSUE_RE.sub(replacement, text)
        return text

    def link(self, link: str, text: str | None = None, title: str | None = None) -> str:
        """Properly format a link."""
        if text or title:
            if not text:
                text = link
            if title:
                paran = f'({link} "{title}")'
            else:
                paran = f"({link})"
            return f"[{text}]{paran}"
        else:
            return link

    def image(self, src: str, alt: str | None = None, title: str | None = None) -> str:
        """Return a link to the provided image."""
        return "!" + self.link(src, text="image", title=alt)

    def emphasis(self, text: str) -> str:
        """Return italiced text."""
        return f"*{text}*"

    def strong(self, text: str) -> str:
        """Return bold text."""
        return f"**{text}**"

    def strikethrough(self, text: str) -> str:
        """Return crossed-out text."""
        return f"~~{text}~~"

    def heading(self, text: str, level: int) -> str:
        """Format the heading normally if it's large enough, or underline it."""
        if level in (1, 2, 3):
            return "#" * level + f" {text.strip()}\n"
        else:
            return f"__{text}__\n"

    def newline(self) -> str:
        """No op."""
        return ""

    # this is for forced breaks like `text  \ntext`; Discord
    def linebreak(self) -> str:
        """Return a new line."""
        return "\n"

    def inline_html(self, html: str) -> str:
        """No op."""
        return ""

    def thematic_break(self) -> str:
        """No op."""
        return ""

    def block_text(self, text: str) -> str:
        """Return text in lists as-is."""
        return text + "\n"

    def block_code(self, code: str, info: str | None = None) -> str:
        """Put the code in a codeblock."""
        md = "```"
        if info is not None:
            info = info.strip()
        if info:
            lang = info.split(None, 1)[0]
            md += lang
        md += "\n"
        return md + code.replace("`" * 3, "`\u200b" * 3) + "\n```\n"

    def block_quote(self, text: str) -> str:
        """Quote the provided text."""
        if text:
            return "> " + "> ".join(text.rstrip().splitlines(keepends=True)) + "\n\n"
        return ""

    def block_html(self, html: str) -> str:
        """No op."""
        return ""

    def block_error(self, html: str) -> str:
        """No op."""
        return ""

    def codespan(self, text: str) -> str:
        """Return the text in a codeblock."""
        char = "``" if "`" in text else "`"
        return char + text + char

    def paragraph(self, text: str) -> str:
        """Return a paragraph with a newline postceeding."""
        return f"{text}\n\n"

    def list(self, text: str, ordered: bool, level: int, start: Any = None) -> str:
        """Return the unedited list."""
        # TODO: figure out how this should actually work
        if level == 1:
            return text.lstrip("\n") + "\n"
        return text

    def list_item(self, text: str, level: int) -> str:
        """Show the list, indented to its proper level."""
        lines = text.rstrip().splitlines()

        prefix = "- "
        result: list[str] = [prefix + lines[0]]

        # just add one level of indentation; any outer lists will indent this again as needed
        indent = " " * len(prefix)
        in_codeblock = "```" in lines[0]
        for line in lines[1:]:
            if not line.strip():
                # whitespace-only lines can be rendered as empty
                result.append("")
                continue

            if in_codeblock:
                # don't indent lines inside codeblocks
                result.append(line)
            else:
                result.append(indent + line)

            # check this at the end, since the first codeblock line should generally be indented
            if "```" in line:
                in_codeblock = not in_codeblock

        return "\n".join(result) + "\n"

    def task_list_item(self, text: Any, level: int, checked: bool = False, **attrs) -> str:
        """Convert task list options to emoji."""
        emoji = constants.Emojis.confirmation if checked else constants.Emojis.no_choice_light
        return self.list_item(emoji + " " + text, level=level)

    def finalize(self, data: Any) -> str:
        """Finalize the data."""
        return "".join(data)
