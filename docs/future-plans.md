# Future plans

These are a list of future plans and integrations for Monty. If you want to help
with one, please open an issue to flesh out the idea a bit more before
contributing.

## Todo

### Core

- Speed up boot time
- Restructure deployments to be able to use RESUMING when deploying a new
    version of Monty (don't lose any events between deployments)
- Use `monty.utils.responses` in more places.
- Type safety
- Enforce `DeleteButton` on *every. single. reply.*

### Database management

- Rewrite guild configuration to be eager upon guild join
- Per-user configuration (see below)

### Dependencies

- Drop some of the additional markdown parsers
- Look into switching to uv from poetry

### Documentation

- Add an autodoc of all app commands to the documentation website.

### GitHub Parsing

- Migrate to Mistune v3
- Rewrite GitHub processing to be more reconfigurable
- Support components v2
- Add image support to replies
- Per user configuration of settings, see below

### User Support

- Per-user configuration
    - documentation objects
    - github org
    - github expand configuration
    - discourse expand
- Per-user Feature system for deployments
- Admin support for user blacklist

## Completed

- Rewrite the developer-side feature view command
- Add contributing documentation
