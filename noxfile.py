#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "nox==2025.5.1",
# ]
# ///
# SPDX-License-Identifier: MIT

from __future__ import annotations

import os
from typing import (
    Any,
    Dict,
    Final,
    List,
    Sequence,
)

import nox


nox.needs_version = ">=2025.5.1"


nox.options.error_on_external_run = True
nox.options.reuse_venv = "yes"
nox.options.default_venv_backend = "uv|virtualenv"

PYPROJECT = nox.project.load_toml()

SUPPORTED_PYTHONS: Final[List[str]] = ["3.10"]
EXPERIMENTAL_PYTHON_VERSIONS: Final[List[str]] = ["3.11", "3.12", "3.13", "3.14"]
ALL_PYTHONS: Final[List[str]] = [*SUPPORTED_PYTHONS, *EXPERIMENTAL_PYTHON_VERSIONS]
MIN_PYTHON: Final[str] = SUPPORTED_PYTHONS[0]
CI: Final[bool] = "CI" in os.environ

# used to reset cached coverage data once for the first test run only
reset_coverage = True


def install_deps(
    session: nox.Session,
    *,
    extras: Sequence[str] | None = None,
    groups: Sequence[str] | None = None,
    project: bool = True,
    dependencies: Sequence[str] | None = None,
) -> None:
    """Helper to install dependencies from a group."""
    command: List[str]

    # If not using uv, install with pip
    if os.getenv("INSTALL_WITH_PIP") is not None:
        command = []
        if project:
            command.append("-e")
            command.append(".")
            if extras:
                # project[extra1,extra2]
                command[-1] += "[" + ",".join(extras) + "]"
        if groups:
            command.extend(nox.project.dependency_groups(PYPROJECT, *groups))
        session.install(*command)

        # install separately in case it conflicts with a just-installed dependency (for overriding a locked dep)
        if dependencies:
            session.install(*dependencies)

        return

    # install with uv
    command = [
        "uv",
        "sync",
        "--no-default-groups",
    ]
    env: Dict[str, Any] = {}

    if session.venv_backend != "none":
        command.append(f"--python={session.virtualenv.location}")
        env["UV_PROJECT_ENVIRONMENT"] = str(session.virtualenv.location)
    elif CI and "VIRTUAL_ENV" in os.environ:
        # we're in CI and using uv, so use the existing venv
        command.append(f"--python={os.environ['VIRTUAL_ENV']}")
        env["UV_PROJECT_ENVIRONMENT"] = os.environ["VIRTUAL_ENV"]

    if extras:
        for e in extras:
            command.append(f"--extra={e}")
    if groups:
        for g in groups:
            command.append(f"--group={g}")
    if not project:
        command.append("--no-install-project")

    session.run_install(
        *command,
        env=env,
        silent=not CI,
    )

    if dependencies:
        if session.venv_backend == "none" and CI:
            # we are not in a venv but we're on CI so we probably intended to do this
            session.run_install("uv", "pip", "install", *dependencies, env=env)
        else:
            session.install(*dependencies, env=env)


@nox.session(default=False)
def docs(session: nox.Session) -> None:
    """Build and generate the documentation."""
    install_deps(session, groups=["docs"])
    args = session.posargs
    session.run(
        "mkdocs",
        "serve",
        *args,
    )


@nox.session
def lint(session: nox.Session) -> None:
    """Check all paths for linting errors."""
    install_deps(session, groups=["tools"])
    session.run("prek", "run", "--all-files", *session.posargs)


@nox.session(name="mdformat")
def mdformat(session: nox.Session) -> None:
    """Run mdformat on the documentation files."""
    install_deps(session, groups=["mdformat"])
    args = session.posargs or ["docs", "README.md", "CONTRIBUTING.md"]
    session.run("mdformat", *args)


@nox.session()
def pyright(session: nox.Session) -> None:
    """Run BasedPyright on Monty."""
    install_deps(
        session,
        groups=[
            "typing",
            "devlibs",
            "nox",
        ],
    )
    env = {
        "PYRIGHT_PYTHON_IGNORE_WARNINGS": "1",
    }

    args = ["--venvpath", session.virtualenv.location, *session.posargs]
    try:
        session.run(
            "python",
            "-m",
            "basedpyright",
            *args,
            env=env,
        )
    except KeyboardInterrupt:
        session.error("Quit pyright")


@nox.session(default=False, python=False)
def dev(session: nox.Session) -> None:
    """
    Set up a development environment using uv.

    This will:
    - lock all dependencies with uv
    - create a .venv/ directory, overwriting the existing one,
    - install all dependencies needed for development.
    - install the pre-commit hook (prek)
    """
    session.run("uv", "lock", external=True)
    session.run("uv", "venv", "--clear", external=True)
    session.run("uv", "sync", "--all-extras", "--all-groups", external=True)
    session.run("uv", "run", "prek", "install", "--overwrite", external=True)


if __name__ == "__main__":
    nox.main()
