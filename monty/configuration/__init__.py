"""
Handle configuration schema.

# The Configuration System

This module defines the configuration schema for Monty, including
default values, validation rules, and serialization/deserialization logic.

Configuration is a complex beast, especially through Discord.

There are multiple sources for configuration, not necessarily in any specific order.

- Default values
- Local environment configuration
- Guild configuration
- User configuration

There is also the matter of mixing in the Features system, which adds another layer of complexity.

## Requirements

### Configuration Sources

- **Default Values**: These are the built-in defaults that Monty uses if no other configuration is provided.
- **Local Environment Configuration**: This includes settings defined in environment variables or local config files.
    These don't really override any of the default values, but they may affect those settings and those options.
    For example, GitHub settings and configuration won't be enabled if the token is not set for GitHub.
- **Guild Configuration**: Guild specific configuration. These can override default values and provide defaults for a
        guild and for user commands within that guild.
- **User Configuration**: User specific configuration. These can override guild configuration and default values for a
        specific user.

The last two have five options for each boolean setting: `always`, `never`, `default`, `true`, and `false`.
In the event that both guild and user configuration are present, the user configuration takes precedence,
with some exceptions. This is best illustrated in the table below:


| Guild   | User    | Result        |
|---------|---------|---------------|
| default | default | bot default   |
| always  | never   | never         |
| always  | true    | always        |
| always  | false   | always        |
| true    | never   | never         |
| false   | never   | never         |
| false   | true    | true          |

Always means the guild will always win, except if the user chose always or never.

A better way to look at this is that "always" is a "force true", and "never" is a "force false".

### Feature Integration

Monty has a feature system that allows for enabling or disabling specific features by the bot owner.
This adds another layer of complexity to the configuration system.

Each feature can be enabled or disabled at the guild or user level, much like the above.
The important aspect about the feature system is that it can lock-out configuration values
and disable commands, options, and even entire extensions. This is important for stability
and ensuring that buggy or experimental features do not affect the entire bot, while still being
available for testing in production.

### UI

The UI of the configuration is a major pain point for this system. The goal is to have a user-friendly interface while
still being entirely in Discord, and being usable if the slash command system is turned off for whatever reason.

One possible way to implement this is with an app command that provides a slash command interface, and a field for
the configuration option.

However, if a user wants to change multiple options, this would require multiple commands, which is not ideal.
Another option is to use a modal, but this has the downside of being limited in the number of fields that can be
displayed. That said, as some configuration options are free-response, a modal may be the only option for those,
if we don't want to lock ourselves to the rigid structure of slash commands.

We are also able to make a sub command for each slash option, but that limits us to only 25 configuration options.

Another concept idea is a slash command for each configuration section, which then provides a list of options
that can be changed. This would allow for a more organized interface, but would still require multiple commands
to change multiple options. This can be used, for example, to open a modal with several selects and a free response
for updating a group of values in one go.

Another option, and perhaps the most user-friendly, is to use a message and interaction based interface.
An entry point with both a prefix and slash command could be implemented to allow users to easily access
the configuration options.
This launches a message with both buttons and selects in order to navigate through the configuration option.
Much like the features interface for admins, this system would allow for easy navigation and configuration of options.

With a button to go-back, and buttons to access each specific section, this would allow us 8 sections per page,
before pagination is required.

## Implementation

Configuration is implemented with Pydantic models, one for each category of configuration. There is a mapping of values
to component type needed.


## Rejected Alternatives

Because this configuration system is tightly coupled with the database, use of SQLModel was considered to handle
the complexity of the configuration schema. However, it wasn't determined to be robust enough for this use case.

Attrs and marshmallow were also considered, but ultimately rejected in favor of Pydantic due to, frankly, it being
written in Rust, and having better performance and type safety.


"""
