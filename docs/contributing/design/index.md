---
description: Design language and best practices
---

# Design

## Language

Monty is intended to have a design language that looks cohesive from one end to
another. All commands and interactions should be consistent between one another.
There are a couple aspects that work together to make this happen, but the core
is:

- Every error message SHOULD be descriptive.
    - A user should be able to figure out what we wrong from the provided error.
    - Tracebacks should ideally not be provided to the end user, though they
        currently are.
- Every reply or message MUST be deletable.
    - A button should be attached to every reply to allow the user to simply press
        it to delete the message, and optionally the command that invoked it too.
    - But they should not delete without the user asking for it to be deleted
- Every message MUST be end-user-friendly.
    - This means using embeds when possible, and providing detailed, grammatically
        correct error messaging.
- Reactions SHOULD never be used as a way for a user to interact with Monty.
    - (there are still some legacy places that use emojis as triggers, please
        submit a fix!)

## Implementations

### Deleting every reply

There are two aspects that work together in order to provide a button to delete
every reply: the button itself, and a listener. All of the buttons are processed
in the
[`monty.exts.core.delete`](https://github.com/onerandomusername/monty-python/blob/main/monty/exts/core/delete.py)
extension.

The DeleteButton itself is defined in `monty.utils.responses`

There is a DeleteButton defined in
[`monty.utils.messages`](https://github.com/onerandomusername/monty-python/blob/main/monty/utils/messages.py),
it should be attached to **all** replies from the bot. If it is not attached to
a message, this is considered a bug and should be fixed. The exception is
ephemeral messages in response to an interaction, as those can be deleted with
the dismiss button provided by Discord.

Known bugs: In some cases the `bookmark` suite of commands does not include
Delete Buttons.

### `monty.utils.responses`

A lot of time and effort has gone into a theoretical unified response system,
but it is not used in very many places yet.

This module is intended to wrap most message replies and be used to send a
response, but it was not implemented in very many places. The proper way to do
this would be to return items in a dictionary form that can then be modified if
needed. Pulls are accepted if you can improve the design language across the
bot.

## Repo layout

### monty

Core source for the bot

#### monty/alembic

Database migrations.

#### monty/database

Model definitions for each database table.

#### monty/exts

Where all of Monty's extension live. They are written with
[disnake](https://docs.disnake.dev/en/stable/) cogs, and follow a typical plan.

- `monty.exts.core`
    - Extensions that run core bot processes.
- `monty.exts.filters`
    - Extensions that listen for messages and provide messaging in reply. Eg a
        token_remover or a webhook deleter, or an unfenced codeblock message.
- `monty.exts.info`
    - Extensions that provide info about *something*, often calling out to an
        external API and performing a search on the user's behalf.
- `monty.exts.meta`
    - Sort of like core, but these are meta commands that allow *end users* to
        interact with the bot. They provide methods or commands for

#### monty/resources

Vendored or other file that needs to be hosted locally and cannot live at an
API.

#### monty/utils

Utility functions that are used by more than one module.
