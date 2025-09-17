# Developer Commands

Monty Python has multiple developer specific commands that can be used within
Discord to manage certain aspects of Monty.

> [!NOTE]
> The following commands are used **within Discord** and should NOT be put into
> a terminal.

### Feature Flags

Some features are locked behind Feature Flags. Monty implements per-server
Feature Flags in order to test new features in production without affecting
other servers. These flags can be enabled on a per-guild basis, or globally.

The dashboard for features is accessible under the `features` command.
Generally, each feature is named with what it corresponds to, but the list of
corresponding features is located in
[`constants.py`](https://github.com/onerandomusername/monty-python/blob/main/monty/constants.py)

### Extension Management

Monty has commands to manage its extension modules in a strong manner, and to
provide developer friendly entrypoints to those working on new features or
bugfixes.

The extension management commands can be used to load or unload specific
extensions or modules for development.

- `ext list`
    - Get a list of all extensions, including their loaded status.
- `ext load [extensions...]`
    - Load extensions given their fully qualified or unqualified names.
- `ext reload [extensions...]`
    - Reload extensions given their fully qualified or unqualified names.
- `ext unload [extensions...]`
    - Unload currently loaded extensions given their fully qualified or
        unqualified names.
- `ext autoreload`
    - Autoreload of modified extensions.

> [!TIP]
> The library that is required for the autoreload command is only installed for
> local development and is not installed within the docker container.

### Eval command

What good would developing be without a developer locked evaluation command?
Monty has a first-class asyncio-compatible evaluation command for the bot owner
only. This command runs within the event loop, and **within the bot context**.

> [!CAUTION]
> Do not run any untrusted data with this command. You could do terrible things
> to your bot and computer.

This command is named `ieval`, short for internal evaluation. It processes with
the same syntax rules as the `eval` command, which uses the snekbox backend, but
is instead run within the bot. This is a developer-only command, as you can
easily print the bot token or do other nefarious things.

```py
-ieval await ctx.send("this is from the bot context!")
```
