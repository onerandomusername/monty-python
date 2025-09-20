---
description: Contributing your changes to Monty Python
---

# Contributing

Thank you for your interest in contributing to Monty!

This document explains the contributing process in full. If your question isn't
answered here, please
[open an issue](https://github.com/onerandomusername/monty-python/issues)

## Issue Tracker

### Reporting a bug

If you find a bug, please report it to
[the issue tracker](https://github.com/onerandomusername/monty-python/issues/new/choose)
with the details of what command you ran, whether or not the bot is in the
server or if you have the bot installed to your user, and the guild ID. This
will help us find the bug so we can fix it.

### Requesting a new feature

If you're looking to submit a new feature, please create an issue on
[the issue tracker](https://github.com/onerandomusername/monty-python/issues/new/choose)
first, so the details can be discussed before submitting. If you have an idea
for a new feature, but don't want to implement it yourself, PLEASE also create
an issue! We love suggestions and new ideas, and want to ensure we're adding
features that the community would actually use! Thank you!

## Submitting a fix

### Overview

The general workflow can be summarized as follows:

1. Fork + clone the repository.
1. Initialize the development environment:
    `poetry install && poetry run prek install`.
1. Create a new branch.
1. Commit your changes, update documentation if required.
1. Push the branch to your fork, and
    [submit a pull request!](https://github.com/onerandomusername/monty-python/pull/new)

### But wait!

Before contributing, **please**
[make an issue](https://github.com/onerandomusername/monty-python/issues/new/choose)
for the specific fix or feature you are attempting to work on: we don't want you
to work on a feature that someone else is already working on, so please check
before you do! Small fixes, such as typos or logic bugs can be fixed without an
issue, but this is best done on a case-by-case basis. If you're wondering, you
can join the [Discord Server](https://discord.gg/mPscM4FjWB) to speak to the
developer at any time.

## Setting up a developer environment

### Requirements

- git
- docker
    - docker compose
- python 3.10
- poetry

Additionally, a postgresql database is required to develop Monty, but this is
included in the developer
[docker-compose.yaml](https://github.com/onerandomusername/monty-python/blob/main/docker-compose.yaml)
file.

If running the bot within docker, most of the following steps can be skipped as
the environment is built within docker automatically. You'll still need to clone
the repository and set up pre-commit hooks.

### Clone the repo

First step to getting started is to clone the repository:

```sh
git clone https://github.com/onerandomusername/monty-python
cd monty-python
```

Next, create a file named `.env` within the cloned repository. This will be used
later regardless of how you run Monty.

A minimum viable contents (if using Docker) are as follows:

```sh
# contents of .env
BOT_TOKEN=...

# to change the default prefix from `-`
PREFIX=...

# optional, used to increase GitHub ratelimits from
# 60 to 5000/h and enable the graphql API
GITHUB_TOKEN=...
```

### Installing dependencies

TLDR:

```sh
poetry install
poetry run prek install
```

If you don't already have poetry installed, check the
[poetry documentation](https://python-poetry.org/), or use a tool like pipx or
uvx.

Make sure you install prek, as it will lint every commit before its
created, limiting the amount of fixes needing to be made in the review process.

### Create a Discord Bot

Go to
[the Discord Developer Portal](https://discord.com/developers/applications) and
click on the "Create Application" button.

Follow the steps through and save the developer token. It needs to go in the
`.env` created earlier.

You'll also need to connect this bot to at least one server you have access to.

> [!WARNING]
> Monty Python requires the message content intent and **won't start** if that
> intent is disabled. Be sure to enable it when configuring the bot.

# Running Monty

From this point, I suggest running two separate docker compose commands. The
first one to run is `docker compose up --detach postgres redis` which starts the
necessary dependent services. If contributing to the eval command, or global
source, then snekbox is also required. The detach flag starts these services but
does not watch them.

### Running outside of Docker

For debugging, I personally run Monty outside of docker, but run the dependent
services within docker. For this to be done, the following configuration is
required in the .env file:

```sh
# within .env
BOT_TOKEN=... # token from earlier
# REQUIRED
DB_BIND='postgresql+asyncpg://monty:monty@localhost:5432/monty'
# to run database migrations/set up the bot for the first time
DB_RUN_MIGRATIONS=true

# optional, for -eval and global source development
SNEKBOX_URL='http://localhost:8060/'

# the redis connection bind if docker compose is running redis
REDIS_URI='redis://default@localhost:6379'
# optional: to only require postgres
USE_FAKEREDIS=true
```

### Running in Docker

If the other services in Docker are already running, simply running the
following should start the bot.

```sh
docker compose up monty
```

Monty should now be running! There's now a few other configuration things to do
to finish initialising the database. See the bot only commands.
