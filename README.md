# Kolumbao

See [Structure](#structure) for an explanation of the file structure.

## Installation
### pip
Firstly, install the required packages,
```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
```
Or alternatively on Windows,
```ps
py -m pip install -r requirements.txt  -r requirements-dev.txt
```

### pre-commit
If you want format checks and formatters to run before commiting, install the pre-commit hooks.
```
pre-commit install
```

Run against all files
```
pre-commit run --all-files
```

Other than manually, pre-commit hooks will run before committing.

### Environment variables
You will need a `.env` or environment variables set as follows:
```dosini
TOKEN=<bot token>
DB_URI=<db uri - anything supported by `SQLAlchemy`>
RABBITMQ_URL=<uri to rabbitmq (including authentication)>

LOG_WEBHOOK=<webhook for logs - discord format>
INFRACTION_LOG=<channel ID to log infractions>
```

Optional environment variables are
```dosini
TOP_CHANNELS_STATS=<list of voice channel ids to show top channels>
HOT_CHANNELS_STATS=<list of voice channel ids to show hottest channels>
MESSAGES_STATS=<voice channel id to show messages received to be sent>
SENTMESSAGES_STATS=<voice channel id to show messages sent across the "network">
```

These allow the bot to store information that can be used by websites using Discord iframes to show details, and the names are in the format:

- For top channels: `channel-name;connected-channels;messages-total;description`
  - For example `kb-general;159;169302;The main channel for Kolumbao, where most topics can be discussed! You may ...`
- For hot channels: `channel-name;messages-this-week;description`
  - For example: `kb-general;229;The main channel for Kolumbao, where most topics can be discussed! You may only sp...`
- For messages, simply the number of messages
  - For example: `239392`
- For sent messages, simply the number of sent messages
  - For example: `8728516`

## Getting started
### Requirements
You must set up a RabbitMQ server, as well as a database. These must be put in the environment variables or a `.env` file.

The bot sends any relevant messages through the RabbitMQ queue to repeaters.

### Running
On most platforms, to run the bot, run
```ps
cd src
python -m bot
```
And the following for the repeater
```ps
cd src
python -m repeater
```

### Windows
On windows, to run the bot, run
```ps
cd src
py -m bot
```
And the following for the repeater
```ps
cd src
py -m repeater
```

### Configuration
A suggested VSCode `launch.json` configuration is:
```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Bot",
            "type": "python",
            "request": "launch",
            "module": "bot",
            "cwd": "${workspaceFolder}/src"
        },
        {
            "name": "Repeater",
            "type": "python",
            "request": "launch",
            "module": "repeater",
            "cwd": "${workspaceFolder}/src"
        }
    ]
}
```

## Docker
- A docker compose file can be found at [docker-compose.yml](docker-compose.yml).
- A docker file can be found at [Dockerfile](Dockerfile).

### Notes
- Data folders for RabbitMQ and the database will show up in the top level.
- You must do `chmod -R 777 rabbitmq` in the root directory. Restart and it'll work.


## Translations
There are numerous translations across the files, and languages can be loaded using `src/core/i18n/get_text.py`. This recursively walks files in the given directory and compiles and translation strings (strings wrapped by `_(` and `)` or `I18n.get_string(` and `)`). Files generated will also declare how they were created.

```python
usage: get_text.py [-h] [-d DIRECTORY] [-t TARGET] [-p PATCH]

Find all i18n text

optional arguments:
  -h, --help            show this help message and exit
  -d DIRECTORY, --directory DIRECTORY
  -t TARGET, --target TARGET
  -p PATCH, --patch PATCH
```

If the `-p` argument is provided, it will fill translations with the translations from a pre-existing file before saving. For example, if new strings were added and needed to be listed for English, you'd do...

```ps
cd src/core/i18n
py ./get_text.py -d ../../.. -t ./translations/en.yaml -p ./translations/en.yaml
```

The `I18n` pre-invoke hook deals with the current locale and sets the currenet context. This is a slightly modified version of the Python package `py18n`. For more specific information and examples, see https://github.com/starsflower/py18n.

## Extras
- This bot uses a modified version of https://github.com/starsflower/multiplehooks, which allows multiple pre/post-invoke hooks to be registered.

  It uses the hooks to register both logging information and i18n contexts.

- The bot uses UUIDs per command context, and error messages contain the UUID for simpler debugging and error reporting. For example:

  ![](https://i.discord.fr/HJW.png)

- The bot can handle replies, and links to the local version of the message being replied to.

  ![](https://i.discord.fr/wvi.png)

## Database
The database will start out empty, but tables will be created automatically.

You will need to create the permissions that the bot uses, and the roles that
use them. If you are the bot owner, you should be able to bypass the majority of permission checks (the bot checks initially if you are the owner, then if you have the permissions).

## Structure
As of [`627d9f5`](https://github.com/Kolumbao/kolumbao/commit/627d9f58ae4558b28f592e570e3bc8b83d363958), this is incorrect. It will be updated in due course once current developments come to a close.
 
```tree
src
|   __init__.py: Specifies version as __version__
|
+---bot
|   |   checks.py: Permission checks, level checks
|   |   converters.py: Custom convertors, such as duration
|   |   errors.py: Custom errors
|   |   format_time.py: Format times and users to be readable
|   |   monkey.py: Monkey patches for the bot, such as the multiplehooks
|   |   paginator.py: Pagintors
|   |   response.py: Unified simple response methods that send as either embeds or text depending on permissions
|   |   __init__.py
|   |   __main__.py
|   |
|   \---extensions
|           blacklist.py: Manage stream blacklists
|           channels.py: Manage your own stream
|           features.py: Manage feature flags
|           installation.py: Get information about installations, and install channels
|           kolumbao.py: Forwards messages to RabbitMQ
|           moderation.py: Moderation commands that mute/warn across the bot (NOT server)
|           roles.py: Manage database roles, which in turn give permissions
|           snippets.py: Manage snippets and send snippets
|           statsync.py: Sync stats with channels defined in .env
|           users.py: Get information about users, their badges, etc
|           __init__.py
|
+---core
|   |   __init__.py
|   |
|   +---db
|   |   |   database.py: Manage database connection, and pre-invoke hook to create database sessions and access easier
|   |   |   utils.py: Get users, guilds, etc from the database or create defaults
|   |   |   __init__.py
|   |   |
|   |   \---models
|   |           announcement.py: Announcement model (deprecated)
|   |           blacklist.py: Blacklist model
|   |           guild.py: Guild model
|   |           infraction.py: Infraction model
|   |           message.py: Message (source) model
|   |           node.py: Node (channel) model
|   |           role.py: Role model and permission model
|   |           snippet.py: Snippet model
|   |           stream.py: Stream model
|   |           user.py: User model
|   |           _types.py: Snowflake custom type
|   |           __init__.py
|   |
|   +---i18n
|   |   |   get_text.py: Create translation files
|   |   |   i18n.py: I18n extension
|   |   |
|   |   \---translations
|   |           en.yaml: English translations
|   |           fr.yaml: French translations
|   |           _empty.yml
|   |
|   +---logs
|   |       log.py: Logging to stdout and webhooks, using custom icons and colors for levels
|   |       __init__.py
|   |
|   +---moderation
|   |       infraction.py: Create/edit infractions
|   |       __init__.py
|   |
|   +---repeater
|   |       client.py: Discord client wrapper over rmqclient.py
|   |       converters.py: Convert messages to RabbitMQ data
|   |       filters.py: Filters messages, such as blacklist or invites
|   |       rmqclient.py: RabbitMQ client wrapper
|   |       __init__.py
|   |
|   +---utils
|   |       download.py: Download file with aiohttp
|   |       ratelimit.py: Custom ratelimiter class
|   |       __init__.py
|   |
|   \---webhook_ext
|           __init__.py: Function to edit webhook messages (discord.py does not support natively)
|
\---repeater
        handlers.py: Handle messages and edits, self ratelimiting with backoff and diagnoses errors and disables NotFound webhooks
        __main__.py: Setup handlers and listen for send/edit messages
```
