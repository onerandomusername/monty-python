import re
from typing import Any, Optional
from urllib.parse import urljoin

import mistune.renderers
from bs4.element import PageElement, Tag
from markdownify import MarkdownConverter


# taken from version 0.6.1 of markdownify
WHITESPACE_RE = re.compile(r"[\r\n\s\t ]+")


class DocMarkdownConverter(MarkdownConverter):
    """Subclass markdownify's MarkdownCoverter to provide custom conversion methods."""

    def __init__(self, *, page_url: str, **options):
        super().__init__(**options)
        self.page_url = page_url

    # overwritten to use our regex from version 0.6.1
    def process_text(self, text: Optional[str]) -> Any:
        """Process the text, using our custom regex."""
        return self.escape(WHITESPACE_RE.sub(" ", text or ""))

    def convert_img(self, el: PageElement, text: str, convert_as_inline: bool) -> str:
        """Remove images from the parsed contents, we don't want them."""
        return ""

    def convert_li(self, el: Tag, text: str, convert_as_inline: bool) -> str:
        """Fix markdownify's erroneous indexing in ol tags."""
        parent = el.parent
        if parent is not None and parent.name == "ol":
            li_tags = parent.find_all("li")
            bullet = f"{li_tags.index(el)+1}."
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

    def convert_hn(self, _n: int, el: PageElement, text: str, convert_as_inline: bool) -> str:
        """Convert h tags to bold text with ** instead of adding #."""
        if convert_as_inline:
            return text
        return f"**{text}**\n\n"

    def convert_code(self, el: PageElement, text: str, convert_as_inline: bool) -> str:
        """Undo `markdownify`s underscore escaping."""
        return f"`{text}`".replace("\\", "")

    def convert_pre(self, el: Tag, text: str, convert_as_inline: bool) -> str:
        """Wrap any codeblocks in `py` for syntax highlighting."""
        code = "".join(el.strings)
        return f"```py\n{code}```"

    def convert_a(self, el: Tag, text: str, convert_as_inline: bool) -> str:
        """Resolve relative URLs to `self.page_url`."""
        href = el["href"]
        assert isinstance(href, str)
        el["href"] = urljoin(self.page_url, href)
        return super().convert_a(el, text, convert_as_inline)

    def convert_p(self, el: PageElement, text: str, convert_as_inline: bool) -> str:
        """Include only one newline instead of two when the parent is a li tag."""
        if convert_as_inline:
            return text

        parent = el.parent
        if parent is not None and parent.name == "li":
            return f"{text}\n"
        return super().convert_p(el, text, convert_as_inline)

    def convert_hr(self, el: PageElement, text: str, convert_as_inline: bool) -> str:
        """Convert hr tags to nothing. This is because later versions added this method."""
        return ""


# todo: this will be expanded over time as necessary
class DiscordRenderer(mistune.renderers.BaseRenderer):
    """Custom renderer for markdown to discord compatiable markdown."""

    def text(self, text: str) -> str:
        """No op."""
        return text

    def link(self, link: str, text: Optional[str] = None, title: Optional[str] = None) -> str:
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

    def image(self, src: str, alt: str = "", title: str = None) -> str:
        """Return a link to the provided image."""
        return self.link(src, text="image", title=title)

    def emphasis(self, text: str) -> str:
        """Return italiced text."""
        return f"*{text}*"

    def strong(self, text: str) -> str:
        """Return bold text."""
        return f"**{text}**"

    def heading(self, text: str, level: int) -> str:
        """Format the heading to be bold if its large enough. Otherwise underline it."""
        if level in (1, 2, 3):
            return f"**{text}**\n"
        else:
            return f"__{text}__\n"

    def newline(self) -> str:
        """Return a new line."""
        return "\n"

    def linebreak(self) -> str:
        """Return two new lines."""
        return "\n\n"

    def inline_html(self, html: str) -> str:
        """No op."""
        return ""

    def thematic_break(self) -> str:
        """No op."""
        return ""

    def block_text(self, text: str) -> str:
        """No op."""
        return text

    def block_code(self, code: str, info: str = None) -> str:
        """Put the code in a codeblock."""
        md = "```"
        if info is not None:
            info = info.strip()
        if info:
            lang = info.split(None, 1)[0]
            md += lang
        return md + code.replace("`" * 3, "`\u200b" * 3) + "\n```"

    def block_quote(self, text: str) -> str:
        """Quote the provided text."""
        if text:
            return "> " + "> ".join(text) + "\n"
        return ""

    def block_html(self, html: str) -> str:
        """No op."""
        return ""

    def block_error(self, html: str) -> str:
        """No op."""
        return ""

    def codespan(self, text: str) -> str:
        """Return the text in a codeblock."""
        return "```\n" + text + "```"

    def paragraph(self, text: str) -> str:
        """Return a paragraph with a newline postceeding."""
        return text + "\n"

    def list(self, text: str, ordered: bool, level: int, start: Any = None) -> str:
        """Do nothing when encountering a list."""
        return ""

    def list_item(self, text: Any, level: int) -> str:
        """Do nothing when encountering a list."""
        return ""

    def finalize(self, data: Any) -> str:
        """Finalize the data."""
        return "".join(data)
