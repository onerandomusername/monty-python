# Monty Python

- [Monty Python](#monty-python)
  - [Primary features](#primary-features)
  - [Running Locally](#running-locally)
  - [Contact](#contact)

Based off of multiple open source projects, Monty is a development tool for Discord servers. See [third party licensing](./LICENSE_THIRD_PARTY) for the original projects.

## Primary features

- `/docs` View and search Python documentation and select libraries
- `/pep` View PEPs directly within Discord
- `/pypi` Search PyPI and view package information
- `-eval` Evaluate Python code
- `-black` Run black over python code

Additionally, Monty features a plethora of GitHub related features, including the following:

- Automatic GitHub issue linking, using the same syntax as GitHub: `org/repo#num`
- Automatic GitHub code embedding, eg when providing a source link to a snippet on GitHub.

Click [here](https://discord.com/oauth2/authorize?client_id=872576125384147005&scope=bot+applications.commands&permissions=395204488384) to invite the public instance of Monty to your Discord server.

## Running Locally

Monty uses quite a few services to run. However, these have been consolidated into the [docker-compose.yaml](./docker-compose.yaml) file.

To deploy, first clone this repo.

Minimally, Monty can run with just a bot token, but a few more variables are recommended for a more full experience.

```sh
# required
BOT_TOKEN=

# optional but recommended
GITHUB_TOKEN= # Generate this in github's api token settings. This does not need any special permissions
```

From this point, just run `docker compose up` to start all of the services. Snekbox is optional, and the bot will function without snekbox.

Some services will not work, but the majority will.

## Contact

For support or to contact the developer, please join the [Support Server](https://discord.gg/mPscM4FjWB).
