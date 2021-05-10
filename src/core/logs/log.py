# -*- coding: utf-8 -*-
import asyncio
import contextvars
import datetime
import logging
import os
import uuid
from typing import Optional

discord_avail = True
try:
    import aiohttp
    import discord  # TODO: possibly unbound discord references later
except ImportError:
    discord_avail = False
    import warnings

    warnings.warn(
        "Missing imports for discord or aiohttp. Both are required for Discord support"
    )


COLORS = {
    logging.DEBUG: discord.Colour.blurple(),
    logging.INFO: discord.Colour.blue(),
    logging.NOTSET: discord.Colour.magenta(),
    logging.ERROR: discord.Colour.red(),
    logging.WARNING: discord.Colour.orange(),
    logging.CRITICAL: discord.Colour.dark_red(),
}
ICONS = {
    logging.DEBUG: "https://cdn.discordapp.com/emojis/784742361745063936.png?v=1",
    logging.INFO: "https://cdn.discordapp.com/emojis/784742361363775489.png?v=1",
    logging.NOTSET: "https://cdn.discordapp.com/emojis/784742361736544267.png?v=1",
    logging.ERROR: "https://cdn.discordapp.com/emojis/784742361796182036.png?v=1",
    logging.WARNING: "https://cdn.discordapp.com/emojis/784742361837469696.png?v=1",
    logging.CRITICAL: "https://cdn.discordapp.com/emojis/784742361825411102.png?v=1",
}


class GlobalDiscordHandler(logging.Handler):
    _ctx = contextvars.ContextVar("ctx")
    _idx = 0

    def __init__(self, url, bot=None):
        super().__init__()
        self.url = url
        if bot:
            self.init_bot(bot)

    def emit(self, record):
        if record.levelno >= self.level:
            asyncio.ensure_future(self.send(record))

    @classmethod
    def init_bot(cls, bot):
        """
        Add a pre-invoke hook that sets the current context for this logger

        Parameters
        ----------
        bot : commands.Bot
            The bot
        """

        async def pre(ctx):
            # Set ctx for context to allow `add_ctx_info` to run.
            cls.set_current_ctx(ctx)

        bot.before_invoke(pre)

    @classmethod
    def set_current_ctx(cls, ctx):
        """
        Set the current context

        Parameters
        ----------
        ctx : commands.Context
            The context
        """
        cls._ctx.set(ctx)

    @classmethod
    def add_ctx_info(cls, embed: discord.Embed):
        """
        Add context info to given embed, or do nothing if no context is set

        Parameters
        ----------
        embed : discord.Embed
            The embed
        """
        ctx = cls._ctx.get(None)
        if ctx is None:
            return

        embed.add_field(name="User", value=f"{ctx.author} ({ctx.author.id})")
        embed.add_field(name="Channel", value=f"{ctx.channel.name} ({ctx.channel.id})")
        embed.add_field(name="Guild", value=f"{ctx.guild.name} ({ctx.guild.id})")

    async def send(self, record: logging.LogRecord):
        async with aiohttp.ClientSession() as client_session:
            webhook = discord.Webhook.from_url(
                self.url, adapter=discord.AsyncWebhookAdapter(client_session)
            )

            # Ensure all logs, even those above 2000 characters, are logged
            string = self.format(record)
            strings = [string]
            if len(string) > 2000:
                # Avoid length limits...
                strings = [string[i : 2000 + i] for i in range(0, len(string), 2000)]

            for s, string in enumerate(strings):
                formatted = (
                    "```python\n{}```".format(string) if record.exc_info else string
                )
                embed = discord.Embed(
                    description=formatted, colour=COLORS[record.levelno]
                )

                if s + 1 == len(strings):
                    self.add_ctx_info(embed)

                embed.set_author(name=record.levelname, icon_url=ICONS[record.levelno])
                embed.set_footer(text=f"UUID {record.uuid}")
                self._idx += 1
                embed.timestamp = datetime.datetime.now()

                await webhook.send(embed=embed, wait=True)


class UUIDFilter(logging.Filter):
    """
    A filter for logs that creates a UUID for the current context

    The current UUID is gettable with `UUIDFilter.get_current_uuid`, and is a
    class method.

    .. warning::
        The UUID is set on `UUIDFilter.filter`. If this is not run, it will
        be ``None``.
    """
    _current_uuid = contextvars.ContextVar("current_uuid")

    @classmethod
    def get_current_uuid(cls, default: Optional[str] = None) -> Optional[str]:
        """
        Get the UUID for the current context

        Parameters
        ----------
        default : str, optional
            The value to return if none has been set, by default None

        Returns
        -------
        str or None
            The UUID
        """
        return cls._current_uuid.get(default)

    def filter(self, record: logging.LogRecord):
        current = UUIDFilter.get_current_uuid()
        if current is None:
            current = str(uuid.uuid4())
            UUIDFilter._current_uuid.set(current)

        record.uuid = current
        return True


initiated_logger = None
default_formatter = logging.Formatter(
    "[%(asctime)s]\t%(time_alive)s\t%(levelname)s\t%(filename)s:%(lineno)d\t%(message)s"
)


def create_general_logger(
    name: str, formatter=default_formatter, level=logging.DEBUG, bot=None
) -> logging.Logger:
    """
    Create a logger. If a logger has already been made, the original logger
    will be used instead of creating another logger.

    .. note::
        If an environment variable named ``LOG_WEBHOOK`` exists and the module
        `discord.py` is available, the function will also automatically add
        webhook logging.

        If a bot exists, it will run `GlobalDiscordHandler.init_bot` on the
        webhook log handler.

    Parameters
    ----------
    name : str
        The name of the logger
    formatter : logging.Formatter, optional
        The log formatter, by default `default_formatter`
    level : int, optional
        Log level, by default `logging.DEBUG`
    bot : commands.Bot, optional
        The bot to add to register any hooks to, by default None

    Returns
    -------
    logging.Logger
        The created logger
    """
    global initiated_logger
    if initiated_logger is not None:
        return initiated_logger

    current_logger = logging.getLogger(name)
    current_logger.setLevel(level)

    class AliveFilter(logging.Filter):
        # Just a simple filter to set the "alive time" in the log.
        start = datetime.datetime.now()

        def filter(self, record):
            record.time_alive = str(datetime.datetime.now() - AliveFilter.start)
            return True

    current_logger.addFilter(UUIDFilter())
    current_logger.addFilter(AliveFilter())

    sh = logging.StreamHandler()
    sh.setLevel(logging.DEBUG)
    sh.setFormatter(formatter)
    current_logger.addHandler(sh)

    if os.getenv("LOG_WEBHOOK") is not None:
        if discord_avail:
            dh = GlobalDiscordHandler(os.getenv("LOG_WEBHOOK"), bot)
            dh.setLevel(level)
            current_logger.addHandler(dh)
        else:
            current_logger.warning(
                "DiscordHandler found LOG_WEBHOOK but "
                "couldn't find the discord module or aiohttp module..."
            )

    initiated_logger = current_logger

    return current_logger
