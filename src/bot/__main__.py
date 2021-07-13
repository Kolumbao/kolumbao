# -*- coding: utf-8 -*-
import concurrent.futures
import logging
import os
from os import getenv

import discord
from discord.ext import commands
from discord.ext.commands.core import is_owner
from discord.ext.commands.errors import CommandNotFound, ExtensionAlreadyLoaded
from discord_components.client import DiscordComponents
from dotenv import load_dotenv
from pretty_help import PrettyHelp

from core.db.models import SharedAttributes
from core.db.models.guild import Guild

from .checks import InsufficientLevel
from .checks import InsufficientPermissions
from .errors import BannedUser, ItemNotFound
from .errors import NotManaging
from .monkey import cache_users_self
from .monkey import multiple_after_invoke
from .monkey import multiple_before_invoke
from .response import bad
from core import db
from core.db import query, session
from core.db.models.user import User
from core.i18n import i18n
from core.i18n.i18n import _
from core.i18n.i18n import I18n
from core.logs.log import create_general_logger
from core.logs.log import UUIDFilter
from core.repeater.client import Client

load_dotenv()

EXTENSIONS = [
    "bot.extensions.kolumbao",
    "bot.extensions.roles",
    "bot.extensions.users",
    "bot.extensions.snippets",
    "bot.extensions.features",
    "bot.extensions.moderation",
    "bot.extensions.installation",
    "bot.extensions.blacklist",
    "bot.extensions.channels",
    "bot.extensions.statsync",
    "bot.extensions.help"
]

bot = commands.Bot(
    command_prefix=commands.when_mentioned_or("kb!", "Kb!"),
    description="Kolumbao is the bot that lets users talk across servers",
    # help_command=PrettyHelp(color=discord.Color.from_rgb(217, 48, 158)),
    intents=discord.Intents.default(),
    allowed_mentions=discord.AllowedMentions(users=True, roles=True),
)
bot.loop.set_default_executor(concurrent.futures.ThreadPoolExecutor())
multiple_after_invoke(bot)
multiple_before_invoke(bot)
# cache_users_self(bot)

database = db.Database(getenv("DB_URI"))


@bot.event
async def on_ready():
    bot.logger = create_general_logger("bot", bot=bot, level=logging.INFO)
    bot.logger.info(f"Ready as {bot.user} in {len(bot.guilds)} guilds...")

    database.init_bot(bot)
    SharedAttributes.init_bot(bot)
    DiscordComponents(bot)

    bot.client = Client(getenv("RABBITMQ_URL"), "default")
    bot.client.init_bot(bot)
    bot.client.set_logger(bot.logger)
    await bot.client.connect()

    bot._ = i18n.I18n(
        {
            "en": os.path.join(
                os.path.dirname(__file__),
                "..",
                "core",
                "i18n",
                "translations",
                "en.yaml",
            ),
            "fr": os.path.join(
                os.path.dirname(__file__),
                "..",
                "core",
                "i18n",
                "translations",
                "fr.yaml",
            ),
        },
        bot=bot,
    )

    bot._.log_missing()

    # Ensure all guilds exist first
    guilds = query(Guild.discord_id).all()
    for guild in bot.guilds:
        if guild.id not in guilds:
            Guild.create(guild)
            session.commit()

    for extension in EXTENSIONS:
        bot.logger.debug("Loading extension %s", extension)

        try:
            bot.load_extension(extension)
        except ExtensionAlreadyLoaded:
            # If we reconnect, make sure the help command is reloaded.
            bot.reload_extension(extension)


@is_owner()
@bot.command()
async def logout(_):
    await bot.close()


def format_missing_perms(missing_perms):
    """
    Format missing perms in the "human" format

    Parameters
    ----------
    missing_perms : list
        List of missing perms

    Returns
    -------
    str
        Formatted string
    """
    missing = [
        perm.lower().replace("_", " ").replace("guild", "server").title()
        for perm in missing_perms
    ]

    if len(missing) > 2:
        fmt = _("PLURAL", values=", ".join(missing[:-1]), final=missing[-1])
    elif len(missing) == 2:
        fmt = _("TWO", first=missing[0], second=missing[1])
    else:
        fmt = missing[0]

    return fmt


# Map error types to a lambda that will return a Coroutine
errors_messages = {
    InsufficientPermissions: lambda error: _(
        "ERROR_INSUFFICIENT_KOLUMBAO_PERMISSIONS",
        permissions=format_missing_perms(error.permissions),
    ),
    commands.MissingRequiredArgument: lambda error: _(
        "ERROR_MISSING_PARAMETER", name=error.param.name
    ),
    commands.UserNotFound: lambda error: _("ERROR_USER_NOT_FOUND", name=error.argument),
    ItemNotFound: lambda error: _(error.message),
    NotManaging: lambda error: _("ERROR_NOT_MANAGING"),
    BannedUser: lambda error: _("ERROR_BANNED", severity=error.level),
    InsufficientLevel: lambda error: _(
        "ERROR_INSUFFICIENT_KOLUMBAO_LEVEL", level=error.level
    ),
    commands.CommandOnCooldown: lambda error: _(
        "ERROR_COOLDOWN", retry_after=error.retry_after
    ),
    commands.BotMissingPermissions: lambda error: _(
        "ERROR_BOT_MISSING_PERMISSIONS",
        permissions=format_missing_perms(error.missing_perms),
    ),
    commands.MissingPermissions: lambda error: _(
        "ERROR_USER_MISSING_PERMISSIONS",
        permissions=format_missing_perms(error.missing_perms),
    ),
    discord.Forbidden: lambda error: _(
        "ERROR_FORBIDDEN",
    )
}


@bot.event
async def on_command_error(ctx: commands.Context, error):
    if isinstance(error, CommandNotFound):
        # Assume a failed command is a snippet
        return await bot.get_cog("Snippets").send_snippet(
            ctx, ctx.invoked_with, I18n.get_current_locale()
        )

    create_message = errors_messages.get(type(error), None)
    if create_message:
        await bad(ctx, create_message(error))
        return
    
    try:
        raise error
    except Exception:
        bot.logger.exception("Unknown command error")
        # Include current UUID for testing
        await bad(ctx, _("ERROR_UNKNOWN", code=UUIDFilter.get_current_uuid()))


@bot.check
async def forbid_banned(ctx: commands.Context):
    if await ctx.bot.is_owner(ctx.author):
        return True

    dbuser = User.create(ctx.author)
    if dbuser.is_banned():
        raise BannedUser(level=dbuser.last_ban().severity)
    
    return True


bot.run(getenv("TOKEN"))
