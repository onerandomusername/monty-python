# Getting Started

## Requirements

- git
- docker
- python 3.10
- poetry

Additionally, a postgresql database is required to develop Monty, but this is
included in the developer
[docker-compose.yaml](https://github.com/onerandomusername/monty-python/blob/main/docker-compose.yaml)
file.

## Setting up a developer environment

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
poetry run pre-commit install
```

If you don't already have poetry installed, check the
[poetry documentation](https://python-poetry.org/), or use a tool like pipx or
uvx.

Make sure you install pre-commit, as it will lint every commit before its
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

## Running Monty

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
