import itertools
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

import mistune.renderers._list
import mistune.renderers.markdown
from bs4.element import PageElement, Tag
from markdownify import MarkdownConverter
from mistune.core import BlockState
from typing_extensions import override

from monty import constants


if TYPE_CHECKING:
    from collections.abc import Iterator


__all__ = (
    "DiscordRenderer",
    "DocMarkdownConverter",
    "remove_codeblocks",
)

RenderToken = dict[str, Any]


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


class DiscordRenderer(mistune.renderers.markdown.MarkdownRenderer):
    """Custom renderer for markdown to discord compatible markdown."""

    def __init__(self, repo: str | None = None) -> None:
        super().__init__()
        self._repo = (repo or "").rstrip("/")

    @override
    def text(self, token: RenderToken, state: BlockState) -> str:
        """Replace GitHub links with their expanded versions."""
        text: str = token["raw"]
        if self._repo:
            # TODO: expand this to all different varieties of automatic links
            # FIXME: this shouldn't expand shorthands inside []() links
            # if a repository is provided we replace all snippets with the correct thing
            def replacement(match: re.Match[str]) -> str:
                full, num = match[0], match[1]
                url = f"{self._repo}/issues/{num}"
                # NOTE: until the above fixme is resolved, we can't use self.link here,
                # since it would recurse indefinitely.
                return f"[{full}]({url})"

            text = GH_ISSUE_RE.sub(replacement, text)
        return text

    # Discord renders links regardless of whether it's `link` or `<link>`
    @override
    def link(self, token: RenderToken, state: BlockState) -> str:
        """Format links, removing unnecessary angle brackets."""
        s = super().link(token, state)
        if s.startswith("<") and s.endswith(">"):
            s = s[1:-1]
        return s

    # provided by plugin, so not part of base MarkdownRenderer
    def strikethrough(self, token: RenderToken, state: BlockState) -> str:
        """Return crossed-out text."""
        text = self.render_children(token, state)
        return f"~~{text}~~"

    @override
    def heading(self, token: RenderToken, state: BlockState) -> str:
        """Format the heading normally if it's large enough, or underline it."""
        level: int = token["attrs"]["level"]
        text = self.render_children(token, state)
        if level in (1, 2, 3):
            return "#" * level + f" {text.strip()}\n"
        else:
            # TODO: consider `-# __text__` for level 5 (smallest) headings?
            return f"__{text}__\n"

    @override
    def inline_html(self, token: RenderToken, state: BlockState) -> str:
        """No op, Discord doesn't render HTML."""
        return ""

    @override
    def thematic_break(self, token: RenderToken, state: BlockState) -> str:
        """No op, Discord doesn't render breaks as horizontal rules."""
        return ""

    # Block code can be fenced by 3+ backticks or 3+ tildes, or be an indented block.
    # Discord only renders code blocks with exactly 3 backticks, so we have to force this format.
    @override
    def block_code(self, token: RenderToken, state: BlockState) -> str:
        """Put code in a codeblock with triple backticks."""
        code: str = token["raw"]
        info: str | None = token.get("attrs", {}).get("info")

        md = "```"
        if info:
            lang = info.strip().split(None, 1)[0]
            if lang:
                md += lang
        md += "\n"

        return md + code.replace("`" * 3, "`\u200b" * 3) + "\n```\n"

    @override
    def block_html(self, token: RenderToken, state: BlockState) -> str:
        """No op, Discord doesn't render HTML."""
        return ""

    @override
    def block_error(self, token: RenderToken, state: BlockState) -> str:
        """No op."""
        return ""

    # Codespans can be delimited with two backticks as well, which allows having
    # single backticks in the contents.
    # Additionally, the delimiters may include one space, e.g. "`` text ``", for text that starts/ends
    # with a backtick. Mistune strips these spaces, but we need them to avoid breaking formatting.
    # Discord renders these spaces (even though they shouldn't), but it's better than no formatting at all.
    # TODO: instead of spaces, we could use \u200b?
    @override
    def codespan(self, token: RenderToken, state: BlockState) -> str:
        """Return the text in a codeblock."""
        text: str = token["raw"]

        delim = "``" if "`" in text else "`"

        if text.startswith("`") or text.endswith("`"):
            text = f" {text} "

        return delim + text + delim

    @override
    def list(self, token: RenderToken, state: BlockState) -> str:
        """Render lists for Discord's (relatively limited subset of) markdown.

        This includes:
        - For ordered lists, enforce 1. instead of 1)
        - For unordered lists, enforce - instead of * or +
          - Discord technically supports *, but might as well use - for all of them
        - Always use "tight" list spacing, Discord does not render loose list items properly

        Moreover, this renders list items with the generic token renderer instead of directly
        calling into list_item(), which allows custom list items (such as `task_list_item`)
        to work (unlike the builtin list renderer :( ).
        """
        prefix_gen: Iterator[str]
        if token["attrs"]["ordered"]:
            start = token["attrs"].get("start", 1)
            prefix_gen = (f"{i}. " for i in itertools.count(start))
        else:
            prefix_gen = itertools.repeat("- ")

        text = ""
        for child, prefix in zip(token["children"], prefix_gen, strict=False):
            child = {**child, "parent": {"leading": prefix}}
            text += self.render_token(child, state)

        # if this is a nested list, strip trailing newlines
        if token.get("parent"):
            text = text.rstrip()
        return text + "\n"

    def list_item(self, token: RenderToken, state: BlockState) -> str:
        """Render a single list item.

        See `list()` above for details.
        """
        for child in token["children"]:
            # force tight list
            if child["type"] == "paragraph":
                child["type"] = "block_text"

        return mistune.renderers._list._render_list_item(self, token["parent"], token, state)

    def task_list_item(self, token: RenderToken, state: BlockState) -> str:
        """Render a task list item, e.g. `- [x] stuff`."""
        checked: bool = token["attrs"]["checked"]
        emoji = constants.Emojis.confirmation if checked else constants.Emojis.no_choice_light

        prefix = {"type": "text", "raw": f"{emoji} "}
        token["children"].insert(0, prefix)

        # treat this like a normal list item now
        return self.list_item(token, state)
