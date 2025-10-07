# App Commands

## Bookmark

Creates personal bookmarks by relaying a message link to the user's DMs.

### `bm`

- `message` (`string`) (required) A message to bookmark. This can be a link or
    id.
- `title` (`string`) An optional title for your direct message.

Bookmark a message.

**Usable in:** `Guilds`

**Installable as:** `Guild`

### `Bookmark`

**Usable in:** `Guilds`, `Private Channels`

**Installable as:** `Guild`, `User`

## Code Block Actions

Adds automatic buttons to codeblocks if they match commands.

### `Format with Black`

**Usable in:** `Guilds`

**Installable as:** `Guild`

### `paste`

- `message` (`string`) (required) A message to paste. This can be a link or id.

Paste a message to the workbin.

**Usable in:** `Guilds`

**Installable as:** `Guild`

### `Run in Snekbox`

**Usable in:** `Guilds`, `Private Channels`

**Installable as:** `Guild`, `User`

### `Upload to Workbin`

**Usable in:** `Guilds`

**Installable as:** `Guild`

## Colour

Cog for the Colour command.

### `colour cymk`

- `cyan` (`integer`) (required) Cyan.

    Constraints: Min: `0`, Max: `100`

- `magenta` (`integer`) (required) Magenta.

    Constraints: Min: `0`, Max: `100`

- `yellow` (`integer`) (required) Yellow.

    Constraints: Min: `0`, Max: `100`

- `black` (`integer`) (required) Black.

    Constraints: Min: `0`, Max: `100`

CMYK Format.

**Usable in:** `Guilds`, `Bot DMs`, `Private Channels`

**Installable as:** `Guild`, `User`

### `colour hex`

- `hex` (`string`) (required) Hex colour code.

HEX Format.

**Usable in:** `Guilds`, `Bot DMs`, `Private Channels`

**Installable as:** `Guild`, `User`

### `colour hsl`

- `hue` (`integer`) (required) Hue.

    Constraints: Min: `0`, Max: `360`

- `sat` (`integer`) (required) Saturation.

    Constraints: Min: `0`, Max: `360`

- `lightness` (`integer`) (required) Lightness.

    Constraints: Min: `0`, Max: `100`

HSL Format.

**Usable in:** `Guilds`, `Bot DMs`, `Private Channels`

**Installable as:** `Guild`, `User`

### `colour hsv`

- `hue` (`integer`) (required) Hue.

    Constraints: Min: `0`, Max: `360`

- `sat` (`integer`) (required) Saturation.

    Constraints: Min: `0`, Max: `360`

- `value` (`integer`) (required) Value.

    Constraints: Min: `0`, Max: `100`

HSV Format.

**Usable in:** `Guilds`, `Bot DMs`, `Private Channels`

**Installable as:** `Guild`, `User`

### `colour name`

- `name` (`string`) (required) Colour name, by close match.

Get a colour by name.

**Usable in:** `Guilds`, `Bot DMs`, `Private Channels`

**Installable as:** `Guild`, `User`

### `colour random`

Random colour.

**Usable in:** `Guilds`, `Bot DMs`, `Private Channels`

**Installable as:** `Guild`, `User`

### `colour rgb`

- `red` (`integer`) (required) Red.

    Constraints: Min: `0`, Max: `255`

- `green` (`integer`) (required) Green.

    Constraints: Min: `0`, Max: `255`

- `blue` (`integer`) (required) Blue.

    Constraints: Min: `0`, Max: `255`

RGB Format.

**Usable in:** `Guilds`, `Bot DMs`, `Private Channels`

**Installable as:** `Guild`, `User`

## Config Manager

Configuration management for each guild.

### `config`

- `category` (`string`) Choose a configuration category to view the options in
    that category. Choices: `⚙️ General bot configuration` (`General`),
    `🐙 GitHub Configuration` (`GitHub`), `🐍 Python tools` (`Python`)

[BETA] Manage per-guild configuration for Monty.

**Usable in:** `Guilds`

**Installable as:** `Guild`

## Discord

Useful discord api commands.

### `discord api`

- `app-info` (`sub_command`) [DEV] Get information on an app from its ID. May
    not work with all apps. Sub-options:

    - `client_id` (`string`) (required) The ID of the app.
    - `ephemeral` (`boolean`) Whether to send the app info as an ephemeral
        message.

- `guild-invite` (`sub_command`) Get information on a guild from an invite.
    Sub-options:

    - `invite` (`string`) (required) The invite to get information on.
    - `ephemeral` (`boolean`) Whether or not to send an ephemeral response.
    - `with_features` (`boolean`) Whether or not to include the features of the
        guild.

-

**Usable in:** `Guilds`, `Bot DMs`, `Private Channels`

**Installable as:** `Guild`, `User`

### `discord api app-info`

- `client_id` (`string`) (required) The ID of the app.
- `ephemeral` (`boolean`) Whether to send the app info as an ephemeral message.

[DEV] Get information on an app from its ID. May not work with all apps.

**Usable in:** `Guilds`, `Bot DMs`, `Private Channels`

**Installable as:** `Guild`, `User`

### `discord api guild-invite`

- `invite` (`string`) (required) The invite to get information on.
- `ephemeral` (`boolean`) Whether or not to send an ephemeral response.
- `with_features` (`boolean`) Whether or not to include the features of the
    guild.

Get information on a guild from an invite.

**Usable in:** `Guilds`, `Bot DMs`, `Private Channels`

**Installable as:** `Guild`, `User`

### `discord app-invite`

- `client_id` (`string`) (required) ID of the user to invite

- `permissions` (`integer`) Value of permissions to pre-fill with

    Constraints: Min: `0`, Max: `4081387162304511`

- `guild_id` (`string`) ID of the guild to pre-fill the invite.

- `raw_link` (`boolean`) Instead of a fancy button, I'll give you the raw link.

- `ephemeral` (`boolean`) Whether or not to send an ephemeral response.

[BETA] Generate an invite to add an app to a guild. NOTE: may not work on all
bots.

**Usable in:** `Guilds`, `Bot DMs`, `Private Channels`

**Installable as:** `Guild`, `User`

## GitHub Information

Fetches info from GitHub.

### `github`

- `arg` (`string`) (required) Can be a org/repo#number, a link to an issue or
    issue comment, and more.

View information about an issue, pull, discussion, or comment on GitHub.

**Usable in:** `Guilds`, `Bot DMs`, `Private Channels`

**Installable as:** `Guild`

## Meta

Get meta information about the bot.

### `monty about`

List features, credits, external links.

**Usable in:** `Guilds`, `Bot DMs`, `Private Channels`

**Installable as:** `Guild`, `User`

### `monty invite`

- `guild_id` (`string`) The guild to prefill the invite link with.
- `raw_link` (`boolean`) Whether to return the raw invite link.
- `ephemeral` (`boolean`) Whether to send the invite link as an ephemeral
    message.

Generate an invite link to invite Monty.

**Usable in:** `Guilds`, `Bot DMs`, `Private Channels`

**Installable as:** `Guild`, `User`

### `monty ping`

Ping the bot to see its latency and state.

**Usable in:** `Guilds`, `Bot DMs`, `Private Channels`

**Installable as:** `Guild`, `User`

### `monty privacy`

- `ephemeral` (`boolean`) Whether to send the privacy information as an
    ephemeral message.

See the privacy policy regarding what information is stored and shared.

**Usable in:** `Guilds`, `Bot DMs`, `Private Channels`

**Installable as:** `Guild`, `User`

### `monty status`

View the current bot status (uptime, guild count, resource usage, etc).

**Usable in:** `Guilds`, `Bot DMs`, `Private Channels`

**Installable as:** `Guild`, `User`

### `monty support`

- `ephemeral` (`boolean`) Whether to send the invite link as an ephemeral
    message.

Get a link to the support server.

**Usable in:** `Guilds`, `Bot DMs`, `Private Channels`

**Installable as:** `Guild`, `User`

## Meta Source

Display information about my own source code.

### `source`

- `item` (`string`) (required) The command or cog to display the source code of.

Get the source of my commands and cogs.

**Usable in:** `Guilds`, `Bot DMs`, `Private Channels`

**Installable as:** `Guild`, `User`

## Misc

A selection of utilities which don't have a clear category.

### `char-info`

- `characters` (`string`) (required) The characters to display information on.

    Constraints: Max length: `50`

Shows you information on up to 50 unicode characters.

**Usable in:** `Guilds`

**Installable as:** `Guild`

### `snowflake`

- `snowflake` (`string`) (required) The snowflake.

[BETA] Get creation date of a snowflake.

**Usable in:** `Guilds`

**Installable as:** `Guild`

## PEPs

Cog for displaying information about PEPs.

### `pep`

- `number` (`integer`) (required) number or search query
- `header` (`string`) If provided, shows a snippet of the PEP at this header.

Fetch information about a PEP.

**Usable in:** `Guilds`, `Bot DMs`, `Private Channels`

**Installable as:** `Guild`, `User`

## PyPI

Cog for getting information about PyPI packages.

### `pypi package`

- `package` (`string`) (required) The package on PyPI to get information about.
- `with_description` (`boolean`) Whether or not to show the full description.

Provide information about a specific package from PyPI.

**Usable in:** `Guilds`, `Bot DMs`, `Private Channels`

**Installable as:** `Guild`, `User`

### `pypi search`

- `query` (`string`) (required) What to search.

- `max-results` (`integer`) Max number of results shown.

    Constraints: Min: `1`, Max: `15`

Search PyPI for a package.

**Usable in:** `Guilds`, `Bot DMs`, `Private Channels`

**Installable as:** `Guild`, `User`

## Ruff

Cog for getting information about Ruff and other rules.

### `ruff rule`

- `rule` (`string`) (required) The rule to get information about

Provide information about a specific rule from ruff.

**Usable in:** `Guilds`, `Bot DMs`, `Private Channels`

**Installable as:** `Guild`, `User`

## Snekbox

Safe evaluation of Python code using Snekbox.

### `eval`

- `code` (`string`) Code to evaluate, leave blank to open a modal.

Evaluate python code.

**Usable in:** `Guilds`, `Private Channels`

**Installable as:** `Guild`, `User`

## XKCD

Retrieving XKCD comics.

### `xkcd`

- `comic` (`string`) number or 'latest'. Leave empty to show a random comic.

View an xkcd comic.

**Usable in:** `Guilds`, `Bot DMs`, `Private Channels`

**Installable as:** `Guild`, `User`
