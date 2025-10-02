import re
import textwrap
from typing import Optional, overload

from monty.log import get_logger


FORMATTED_CODE_REGEX = re.compile(
    r"(?P<delim>(?P<block>```)|``?)"  # code delimiter: 1-3 backticks; (?P=block) only matches if it's a block
    r"(?(block)(?:(?P<lang>[a-z]+)\n)?)"  # if we're in a block, match optional language (only letters plus newline)
    r"(?:[ \t]*\n)*"  # any blank (empty or tabs/spaces only) lines before the code
    r"(?P<code>.*?)"  # extract all code inside the markup
    r"\s*"  # any more whitespace before the end of the code markup
    r"(?P=delim)",  # match the exact same delimiter from the start again
    re.DOTALL | re.IGNORECASE,  # "." also matches newlines, case insensitive
)
RAW_CODE_REGEX = re.compile(
    r"^(?:[ \t]*\n)*"  # any blank (empty or tabs/spaces only) lines before the code
    r"(?P<code>.*?)"  # extract all the rest as code
    r"\s*$",  # any trailing whitespace until the end of the string
    re.DOTALL,  # "." also matches newlines
)
log = get_logger(__name__)


@overload
def prepare_input(code: str, *, require_fenced: bool = False) -> str: ...


@overload
def prepare_input(code: str, *, require_fenced: bool = True) -> Optional[str]: ...


def prepare_input(code: str, *, require_fenced: bool = False) -> Optional[str]:
    """
    Extract code from the Markdown, format it, and insert it into the code template.

    If there is any code block, ignore text outside the code block.
    Use the first code block, but prefer a fenced code block.
    If there are several fenced code blocks, concatenate only the fenced code blocks.
    """
    if match := list(FORMATTED_CODE_REGEX.finditer(code)):
        blocks = [block for block in match if block.group("block")]

        if len(blocks) > 1:
            code = "\n".join(block.group("code") for block in blocks)
            info = "several code blocks"
        else:
            match = match[0] if len(blocks) == 0 else blocks[0]
            code, block, lang, delim = match.group("code", "block", "lang", "delim")
            if block:
                info = (f"'{lang}' highlighted" if lang else "plain") + " code block"
            else:
                info = f"{delim}-enclosed inline code"
    elif require_fenced:
        return None
    elif match := RAW_CODE_REGEX.fullmatch(code):
        code = match.group("code")
        info = "unformatted or badly formatted code"

    code = textwrap.dedent(code)
    log.trace("Extracted %s for evaluation:\n%s", info, code)
    return code
