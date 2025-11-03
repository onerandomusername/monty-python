# Prefix Commands

## Bookmark

Creates personal bookmarks by relaying a message link to the user's DMs.

### `bookmark <target_message> [title=Bookmark]`

*Send the author a link to `target_message` via DMs.*

**Can also use:** `bm`, `pin`

## Code Block Actions

Adds automatic buttons to codeblocks if they match commands.

### `blackify [message=None]`

*Format the provided message with black.*

**Can also use:** `bl`, `black`

### `paste [message=None]`

*Paste the contents of the provided message on workbin.*

**Can also use:** `p`

## Colour

Cog for the Colour command.

### `colour [colour_input=None]`

*Create an embed that displays colour information.*

**Can also use:** `color`

### `colour cmyk <cyan> <magenta> <yellow> <black>`

*Create an embed from a CMYK input.*

### `colour hex <hex_code>`

*Create an embed from a HEX input.*

### `colour hsl <hue> <saturation> <lightness>`

*Create an embed from an HSL input.*

### `colour hsv <hue> <saturation> <value>`

*Create an embed from an HSV input.*

### `colour name <name>`

*Create an embed from a name input.*

### `colour random`

*Create an embed from a randomly chosen colour.*

### `colour rgb <red> <green> <blue>`

*Create an embed from an RGB input.*

## Extensions

Extension management commands.

### `extensions`

*Load, unload, reload, and list loaded extensions.*

**Can also use:** `c`, `cogs`, `ext`, `exts`

### `extensions autoreload`

*Autoreload of modified extensions.*

**Can also use:** `extensions ar`

### `extensions autoreload disable`

*Disable extension autoreload.*

### `extensions autoreload enable [extra_paths...]`

*Enable extension autoreload.*

### `extensions list`

*Get a list of all extensions, including their loaded status.*

**Can also use:** `extensions all`

### `extensions load [extensions...]`

*Load extensions given their fully qualified or unqualified names.*

**Can also use:** `extensions l`

### `extensions reload [extensions...]`

*Reload extensions given their fully qualified or unqualified names.*

**Can also use:** `extensions r`, `reload`

### `extensions unload [extensions...]`

*Unload currently loaded extensions given their fully qualified or unqualified
names.*

**Can also use:** `extensions ul`

## Feature Management

Management commands for bot features.

### `features [arg=None] [show_all=None]`

*Manage features.*

### `features add [guilds=None] [names...]`

*Add the features to the provided guilds, defaulting to the local guild.*

**Can also use:** `features a`, `features enable`

### `features guild`

*Show the features for the current guild.*

### `features remove [guilds=None] [names...]`

*Remove the features from the provided guilds, defaulting to the local guild.*

**Can also use:** `features disable`, `features r`

## GitHub Information

Fetches info from GitHub.

### `github [args...]`

*Group for GitHub related commands.*

**Can also use:** `gh`

### `github repo <user_and_repo> [repo=]`

*Fetch GitHub repository information.*

### `github user <user>`

*Fetch GitHub user information.*

## Help

Custom disnake.Embed Pagination Help feature.

### `help [commands...]`

*Shows Command Help.*

## HTTP Status Codes

Fetch an image depicting HTTP status codes as a dog or a cat or as goat.

If neither animal is selected a cat or dog or goat is chosen randomly for the
given status code.

### `http_status <code>`

*Choose an animal randomly for the given status code.*

**Can also use:** `http`, `httpstatus`, `status`

### `http_status cat <code>`

*Sends an embed with an image of a cat, portraying the status code.*

### `http_status dog <code>`

*Sends an embed with an image of a dog, portraying the status code.*

### `http_status goat <code>`

*Sends an embed with an image of a goat, portraying the status code.*

## Meta Source

Display information about my own source code.

### `source [source_item=None]`

*Display information and a GitHub link to the source code of a command or cog.*

**Can also use:** `src`

## Misc

A selection of utilities which don't have a clear category.

### `snowflake [snowflakes...]`

*Get Discord snowflake creation time.*

**Can also use:** `sf`, `snf`, `snfl`

## Real Python

User initiated command to search for a Real Python article.

### `realpython <user_search>`

*Send 5 articles that match the user's search terms.*

**Can also use:** `rp`

## Rollouts

Management commands for bot rollouts.

### `rollouts`

*Manage feature rollouts.*

**Can also use:** `rollout`

### `rollouts create <name> <percent_goal>`

*Create a rollout.*

### `rollouts delete <rollout>`

*Delete an existing rollout. There is no going back.*

### `rollouts link`

*Manage rollout links to features and other components.*

**Can also use:** `rollouts unlink`

### `rollouts link feature <rollout> <feature>`

*Link or unlink a feature from the specified rollout.*

### `rollouts list`

*List all rollouts and their current status.*

### `rollouts modify <rollout> <new_percent>`

*Configure an existing rollout.*

### `rollouts start <rollout> <dt>`

*Start a rollout now to end at the specified time.*

### `rollouts stop <rollout>`

*Stop a rollout. This does not decrease the rollout amount, just stops
increasing the rollout.*

**Can also use:** `rollouts halt`

### `rollouts view <rollout>`

*Show information about a rollout.*

**Can also use:** `rollouts show`

## Snekbox

Safe evaluation of Python code using Snekbox.

### `eval [code=None]`

*Run Python code and get the results.*

**Can also use:** `e`

### `snekbox`

*Commands for managing the snekbox instance.*

**Can also use:** `snek`

### `snekbox packages`

*Manage the packages installed on snekbox.*

**Can also use:** `snekbox p`, `snekbox pack`, `snekbox packs`

### `snekbox packages add [packages...]`

*Install the specified packages to snekbox.*

**Can also use:** `snekbox packages a`, `snekbox packages install`

### `snekbox packages list`

*List all packages on snekbox.*

**Can also use:** `snekbox packages l`

### `snekbox packages remove [packages...]`

*Uninstall the provided package from snekbox.*

**Can also use:** `snekbox packages d`, `snekbox packages del`,
`snekbox packages delete`, `snekbox packages r`, `snekbox packages uninstall`

### `snekbox packages view <package>`

*View more specific details about a single package installed on snekbox.*

**Can also use:** `snekbox packages info`, `snekbox packages show`

## Stack Overflow

Contains command to interact with stackoverflow from disnake.

### `stackoverflow <search_query>`

*Sends the top 5 results of a search query from stackoverflow.*

**Can also use:** `so`

## Timed Commands

Time the command execution of a command.

### `timed <command>`

*Time the command execution of a command.*

**Can also use:** `t`, `time`

## Wikipedia Search

Get info from wikipedia.

### `wikipedia <search>`

*Sends paginated top 10 results of Wikipedia search..*

**Can also use:** `wiki`
