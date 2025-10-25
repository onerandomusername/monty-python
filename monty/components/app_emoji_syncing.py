from __future__ import annotations

import asyncio
import datetime
import pathlib
from typing import TYPE_CHECKING, Protocol


if TYPE_CHECKING:
    from asyncio.subprocess import Process
    from collections.abc import Generator

    from monty.github_client import GitHubClient


class EmojiContentNotFoundError(Exception):
    """Exception raised when the content of an emoji is not found."""


class AppEmojiSyncer(Protocol):
    async def get_last_changed_date(self) -> datetime.datetime:
        """Provide the timestamp of the most recent change for the emoji directory."""
        ...

    async def get_emoji_content(self, emoji_name: str) -> bytes:
        """Provide the content of the specified emoji."""
        ...


class GitHubBackend:
    def __init__(self, github_client: GitHubClient, *, user: str, repo: str, emoji_directory: str, sha: str):
        self.github = github_client
        self.user = user
        self.repo = repo
        self.emoji_directory = emoji_directory
        self.sha = sha

    async def get_last_changed_date(self) -> datetime.datetime:
        """Get the time of the last commit for the emoji directory."""
        resp = await self.github.rest.repos.async_list_commits(
            owner=self.user,
            repo=self.repo,
            per_page=1,
            path=self.emoji_directory,
            sha=self.sha,
        )
        commits = resp.parsed_data
        if not commits:
            return datetime.datetime.now(tz=datetime.timezone.utc)
        commit = commits[0]

        committer = commit.commit.committer or commit.commit.author
        last_changed = None
        if committer:
            last_changed = committer.date
        if not last_changed:
            # assume it was just changed and do a full sync
            last_changed = datetime.datetime.now(tz=datetime.timezone.utc)
        return last_changed

    async def get_emoji_content(self, emoji_name: str) -> bytes:
        """Get the content of the emoji image."""
        r = await self.github.rest.repos.async_get_content(
            owner=self.user,
            repo=self.repo,
            path=f"{self.emoji_directory}/{emoji_name}.png",
            ref=self.sha,
            headers={"Accept": "application/vnd.github.raw+json"},
        )
        return r.content


class LocalGitBackend:
    def __init__(self, emoji_directory: str, sha: str | None = None):
        self.repo_path = pathlib.Path.cwd()
        emoji_directory_path = pathlib.Path(emoji_directory)
        if emoji_directory_path.anchor:
            emoji_directory_path = pathlib.Path(*emoji_directory_path.parts[1:])
        self.emoji_directory = (self.repo_path / emoji_directory_path.resolve()).relative_to(self.repo_path)
        self.sha = sha or "HEAD"

    def _list_local_files(self) -> Generator[pathlib.Path, None, None]:
        """List all local emoji files."""
        yield from (self.repo_path / self.emoji_directory).rglob("*.png")

    async def get_last_changed_date(self) -> datetime.datetime:
        """Get the time of the last commit for the emoji directory."""
        if self.sha == "HEAD":
            # check modified files with pathlib
            last_changed: datetime.datetime = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
            for file in self._list_local_files():
                file_mtime = file.stat().st_mtime
                if file_mtime > last_changed.timestamp():
                    last_changed = datetime.datetime.fromtimestamp(file_mtime, tz=datetime.timezone.utc)
            return last_changed

        proc = await asyncio.create_subprocess_exec(
            "git",
            "log",
            "-1",
            "--format=%ct",
            self.sha,
            cwd=self.repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            msg = f"Git command failed: {stderr.decode().strip()}"
            raise RuntimeError(msg)
        timestamp = int(stdout.decode().strip())
        return datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)

    async def get_emoji_content(self, emoji_name: str) -> bytes:
        """Read the emoji at the specified path."""
        path = f"{self.emoji_directory}/{emoji_name}.png"
        if self.sha == "HEAD":
            # fetch the existing files at this exact moment
            file_path = self.repo_path / self.emoji_directory / f"{emoji_name}.png"
            if not file_path.exists():
                msg = f"Emoji file not found: {file_path}"
                raise EmojiContentNotFoundError(msg)
            with file_path.open("rb") as f:
                return f.read()

        cmd = f"git show {self.sha}:{path}"
        proc: Process = await asyncio.create_subprocess_exec(
            *cmd.split(),
            cwd=self.repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            msg = f"Git command failed: {stderr.decode().strip()}"
            raise RuntimeError(msg)
        return stdout
