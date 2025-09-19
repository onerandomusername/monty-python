# Prefix Commands

## Admin

Admin-only eval command and repr.

### `gateway`

**`gateway [events...]`** **Can also use:** `gw`

*Sends current stats from the gateway.*

### `inter-eval`

**`inter-eval <code>`** *Sends a message with a button to evaluate code.*

## Bookmark

Creates personal bookmarks by relaying a message link to the user's DMs.

### `bookmark`

**`bookmark <target_message> [title=Bookmark]`** **Can also use:** `bm`, `pin`

*Send the author a link to `target_message` via DMs.*

## Code Block Actions

Adds automatic buttons to codeblocks if they match commands.

### `blackify`

**`blackify [message=None]`** **Can also use:** `bl`, `black`

*Format the provided message with black.*

### `paste`

**`paste [message=None]`** **Can also use:** `p`

*Paste the contents of the provided message on workbin.*

## Colour

Cog for the Colour command.

### `colour`

**`colour [colour_input=None]`** **Can also use:** `color`

*Create an embed that displays colour information.*

### `colour cmyk`

**`colour cmyk <cyan> <magenta> <yellow> <key>`** *Create an embed from a CMYK
input.*

### `colour hex`

**`colour hex <hex_code>`** *Create an embed from a HEX input.*

### `colour hsl`

**`colour hsl <hue> <saturation> <lightness>`** *Create an embed from an HSL
input.*

### `colour hsv`

**`colour hsv <hue> <saturation> <value>`** *Create an embed from an HSV input.*

### `colour name`

**`colour name <name>`** *Create an embed from a name input.*

### `colour random`

**`colour random `** *Create an embed from a randomly chosen colour.*

### `colour rgb`

**`colour rgb <red> <green> <blue>`** *Create an embed from an RGB input.*

## Extensions

Extension management commands.

### `extensions`

**`extensions `** **Can also use:** `c`, `cogs`, `ext`, `exts`

*Load, unload, reload, and list loaded extensions.*

### `extensions autoreload`

**`extensions autoreload `** **Can also use:** `extensions ar`

*Autoreload of modified extensions.*

### `extensions autoreload disable`

**`extensions autoreload disable `** *Disable extension autoreload.*

### `extensions autoreload enable`

**`extensions autoreload enable `** *Enable extension autoreload.*

### `extensions list`

**`extensions list `** **Can also use:** `extensions all`

*Get a list of all extensions, including their loaded status.*

### `extensions load`

**`extensions load [extensions...]`** **Can also use:** `extensions l`

*Load extensions given their fully qualified or unqualified names.*

### `extensions reload`

**`extensions reload [extensions...]`** **Can also use:** `extensions r`,
`reload`

*Reload extensions given their fully qualified or unqualified names.*

### `extensions unload`

**`extensions unload [extensions...]`** **Can also use:** `extensions ul`

*Unload currently loaded extensions given their fully qualified or unqualified
names.*

## Feature Management

Management commands for bot features.

### `features`

**`features [arg=None] [show_all=None]`** *Manage features.*

### `features add`

**`features add [guilds=None] [names...]`** **Can also use:** `features a`,
`features enable`

*Add the features to the provided guilds, defaulting to the local guild.*

### `features guild`

**`features guild `** *Show the features for the current guild.*

### `features remove`

**`features remove [guilds=None] [names...]`** **Can also use:**
`features disable`, `features r`

*Remove the features from the provided guilds, defaulting to the local guild.*

## GitHub Information

Fetches info from GitHub.

### `github`

**`github [user_or_repo=]`** **Can also use:** `gh`, `git`

*Commands for finding information related to GitHub.*

### `github issue`

**`github issue <numbers> <repo> [user=None]`** **Can also use:** `github pr`,
`github pull`

*Command to retrieve issue(s) from a GitHub repository.*

### `github repository`

**`github repository [repo...]`** **Can also use:** `github repo`, `repo`

*Fetches a repositories' GitHub information.*

### `github user`

**`github user <username>`** **Can also use:** `github userinfo`

*Fetches a user's GitHub information.*

## Help

Custom disnake.Embed Pagination Help feature.

### `help`

**`help [commands...]`** *Shows Command Help.*

## HTTP Status Codes

```
Fetch an image depicting HTTP status codes as a dog or a cat.

If neither animal is selected a cat or dog is chosen randomly for the given status code.
```

### `http_status`

**`http_status <code>`** **Can also use:** `http`, `httpstatus`, `status`

*Choose a cat or dog randomly for the given status code.*

### `http_status cat`

**`http_status cat <code>`** *Sends an embed with an image of a cat, portraying
the status code.*

### `http_status dog`

**`http_status dog <code>`** *Sends an embed with an image of a dog, portraying
the status code.*

## Meta Source

Display information about my own source code.

### `source`

**`source [source_item=None]`** **Can also use:** `src`

*Display information and a GitHub link to the source code of a command or cog.*

## Misc

A selection of utilities which don't have a clear category.

### `snowflake`

**`snowflake [snowflakes...]`** **Can also use:** `sf`, `snf`, `snfl`

*Get Discord snowflake creation time.*

## Real Python

User initiated command to search for a Real Python article.

### `realpython`

**`realpython <user_search>`** **Can also use:** `rp`

*Send 5 articles that match the user's search terms.*

## Rollouts

Management commands for bot rollouts.

### `rollouts`

**`rollouts `** **Can also use:** `rollout`

*Manage feature rollouts.*

### `rollouts create`

**`rollouts create <name> <percent_goal>`** *Create a rollout.*

### `rollouts delete`

**`rollouts delete <rollout>`** *Delete an existing rollout. There is no going
back.*

### `rollouts link`

**`rollouts link `** **Can also use:** `rollouts unlink`

*Manage rollout links to features and other components.*

### `rollouts link feature`

**`rollouts link feature <rollout> <feature>`** *Link or unlink a feature from
the specified rollout.*

### `rollouts list`

**`rollouts list `** *List all rollouts and their current status.*

### `rollouts modify`

**`rollouts modify <rollout> <new_percent>`** *Configure an existing rollout.*

### `rollouts start`

**`rollouts start <rollout> <dt>`** *Start a rollout now to end at the specified
time.*

### `rollouts stop`

**`rollouts stop <rollout>`** **Can also use:** `rollouts halt`

*Stop a rollout. This does not decrease the rollout amount, just stops
increasing the rollout.*

### `rollouts view`

**`rollouts view <rollout>`** **Can also use:** `rollouts show`

*Show information about a rollout.*

## Snekbox

Safe evaluation of Python code using Snekbox.

### `eval`

**`eval [code=None]`** **Can also use:** `e`

*Run Python code and get the results.*

### `snekbox`

**`snekbox `** **Can also use:** `snek`

*Commands for managing the snekbox instance.*

### `snekbox packages`

**`snekbox packages `** **Can also use:** `snekbox p`, `snekbox pack`,
`snekbox packs`

*Manage the packages installed on snekbox.*

### `snekbox packages add`

**`snekbox packages add [packages...]`** **Can also use:** `snekbox packages a`,
`snekbox packages install`

*Install the specified packages to snekbox.*

### `snekbox packages list`

**`snekbox packages list `** **Can also use:** `snekbox packages l`

*List all packages on snekbox.*

### `snekbox packages remove`

**`snekbox packages remove [packages...]`** **Can also use:**
`snekbox packages d`, `snekbox packages del`, `snekbox packages delete`,
`snekbox packages r`, `snekbox packages uninstall`

*Uninstall the provided package from snekbox.*

### `snekbox packages view`

**`snekbox packages view <package>`** **Can also use:** `snekbox packages info`,
`snekbox packages show`

*View more specific details about a single package installed on snekbox.*

## Stack Overflow

Contains command to interact with stackoverflow from disnake.

### `stackoverflow`

**`stackoverflow <search_query>`** **Can also use:** `so`

*Sends the top 5 results of a search query from stackoverflow.*

## Timed Commands

Time the command execution of a command.

### `timed`

**`timed <command>`** **Can also use:** `t`, `time`

*Time the command execution of a command.*

## Wikipedia Search

Get info from wikipedia.

### `wikipedia`

**`wikipedia <search>`** **Can also use:** `wiki`

*Sends paginated top 10 results of Wikipedia search..*
