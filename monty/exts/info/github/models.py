# pyright: reportUnannotatedClassAttribute=false
from __future__ import annotations

import datetime as datetime  # noqa: TC003
from typing import TYPE_CHECKING, Annotated, Literal, NamedTuple, Self, cast, override

from pydantic import (
    AliasChoices,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
)


if TYPE_CHECKING:
    from githubkit.versions.latest.models import IssuePropLabelsItemsOneof1


def state_validator(value: object) -> bool:
    match value:
        case bool():
            return value
        case "open" | "closed":
            return value == "closed"
        case _:
            msg = "`closed` must be a bool or a string of 'open' or 'closed'"
            raise ValueError(msg)


class GitHubUser(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(alias="login")
    # `html_url` comes before `url` to prefer the human-readable GitHub page link when
    # both fields are present
    url: str = Field(validation_alias=AliasChoices("html_url", "url"))
    icon_url: str = Field(validation_alias=AliasChoices("icon_url", "avatar_url"))

    @property
    def hyperlink(self) -> str:
        return f"[`{self.name}`](<{self.url}>)"

    @classmethod
    def default(cls) -> Self:
        return cls(
            login="GitHub",
            url="https://github.com",
            icon_url="https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png",
        )


class Reactions(BaseModel):
    model_config = ConfigDict(frozen=True)

    plus_one: int
    minus_one: int
    laugh: int
    confused: int
    heart: int
    hooray: int
    eyes: int
    rocket: int


class Entity(BaseModel):
    model_config = ConfigDict(frozen=True)

    number: int
    title: str
    body: str | None
    reactions: Reactions | None = None
    html_url: str
    user: GitHubUser
    created_at: datetime.datetime

    def _owner_and_repo(self) -> tuple[str, str]:
        owner, repo, _ = self.html_url.removeprefix("https://github.com/").split("/", 2)
        return owner, repo

    @property
    def owner(self) -> str:
        return self._owner_and_repo()[0]

    @property
    def repo_name(self) -> str:
        return self._owner_and_repo()[1]

    @property
    def kind(self) -> str:
        if not (name := type(self).__name__):
            return name
        return name[0] + "".join(f" {c}" if c.isupper() else c for c in name[1:])


class Issue(Entity):
    closed: Annotated[bool, Field(alias="state"), BeforeValidator(state_validator)]
    state_reason: Literal["completed", "reopened", "not_planned", "duplicate"] | None
    labels: tuple[str, ...]  # a tuple so that the model is hashable

    @field_validator("labels", mode="before")
    @classmethod
    def extract_name(cls, value: list[IssuePropLabelsItemsOneof1]) -> tuple[str, ...]:
        return tuple(cast("str", label.name) for label in value)


class PullRequest(Entity):
    closed: Annotated[bool, Field(alias="state"), BeforeValidator(state_validator)]
    draft: bool
    merged: bool
    additions: int
    deletions: int
    changed_files: int


class Discussion(Entity):
    answered_by: GitHubUser | None
    closed: bool
    state_reason: Literal["DUPLICATE", "RESOLVED", "OUTDATED", "REOPENED"] | None


class EntityGist(NamedTuple):
    owner: str
    repo: str
    number: int

    @override
    def __str__(self) -> str:
        return f"{self.owner}/{self.repo}#{self.number}"


class Comment(BaseModel):
    model_config = ConfigDict(frozen=True)

    author: GitHubUser
    body: str
    reactions: Reactions | None = None
    entity: Entity
    entity_gist: EntityGist
    created_at: datetime.datetime
    html_url: str
    kind: str = "Comment"
    color: int | None = None

    @field_validator("body", mode="before")
    @classmethod
    def _truncate_body(cls, value: object) -> str:
        if not (isinstance(value, str) or value is None):
            msg = "`body` must be a string or None"
            raise ValueError(msg)
        return (value or "")[:4096]
