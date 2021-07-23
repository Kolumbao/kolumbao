# -*- coding: utf-8 -*-
import asyncio
from collections import defaultdict
from datetime import time
import threading
import types
from os import getenv

import discord
from discord.ext import commands
from discord.http import HTTPClient
from discord.state import ConnectionState


def multiple_before_invoke(bot: commands.Bot):
    """Changes the before invoke of bot to automatically register multiple
    before-invocation hooks.

    Args:
        bot (commands.Bot): The bot to change the before-invoke hook of.
    """
    bot._before_invokes = []  # noqa

    async def invoke_caller(ctx):
        for hook in bot._before_invokes:  # noqa
            await hook(ctx)

    bot._before_invoke = invoke_caller  # noqa

    def before_invoke(coro):
        bot._before_invokes.append(coro)  # noqa

    bot.before_invoke = before_invoke  # noqa


def multiple_after_invoke(bot: commands.Bot):
    """Changes the after invoke of bot to automatically register multiple
    after-invocation hooks.

    Args:
        bot (commands.Bot): The bot to change the after-invoke hook of.
    """
    bot._after_invokes = []  # noqa

    async def invoke_caller(ctx):
        for hook in bot._after_invokes:  # noqa
            await hook(ctx)

    bot._after_invoke = invoke_caller  # noqa

    def after_invoke(coro):
        bot._after_invokes.append(coro)  # noqa

    bot.after_invoke = after_invoke  # noqa


def cache_users_self(bot: commands.Bot, expiry_time_seconds: float = 30 * 60):
    """
    Override cache handling to mimick member intents if it is not enabled.

    .. warning::
        This is very unstable, and not recommended to be used. This also could
        potentially cause breaking changes in the bot if discord.py updates how
        internal fetching works.

    .. seealso::
        It is preferable to use actual intents. If intents are enable, this
        method will do nothing anyway, but it is best to keep away from using
        thins function.

    Parameters
    ----------
    bot : commands.Bot
        The bot to monkey patch
    expiry_time_seconds : float
        The amount of time before considering an entry "expired", by default
        30 minutes.
    """
    # Don't override if intents are enabled
    if bot.intents.members:
        return

    # Setup a seperate loop and http client
    new_loop = asyncio.new_event_loop()
    
    # Start the thread loop in the background
    threading.Thread(target=new_loop.run_forever, daemon=False).start()
    
    # And start the seperate http client
    bot._seperate_http = HTTPClient(unsync_clock=True, loop=new_loop)
    asyncio.run_coroutine_threadsafe(
        bot._seperate_http.static_login(getenv("TOKEN"), bot=bot), new_loop
    )

    _cache = defaultdict(lambda: 0)
    def _get_user(self, user_id) -> discord.User:
        user = self._connection.get_user(user_id)
        cache_age = time() - _cache.get(user_id)

        # If the user doesn't exist or the cache is expired
        if user is None or cache_age > expiry_time_seconds:
            data = asyncio.run_coroutine_threadsafe(
                self._seperate_http.get_user(user_id), new_loop
            )
            if data.exception() is None:
                _cache[user_id] = time()
                return self._connection.store_user(data=data.result())

            return None
        return user

    # Override the store user mechanism, even if the intents are off
    bot._connection.store_user = types.MethodType(
        ConnectionState.store_user, bot._connection
    )
    
    # Override the get_user functionality
    bot.get_user = types.MethodType(_get_user, bot)

    # Override fetch_user to save result
    async def _fetch_user(self, user_id) -> discord.User:
        data = await self.http.get_user(user_id)
        return self._connection.store_user(data=data)

    # Override the fetch to use our own 'get_user' method so that it saves the
    # result
    bot.fetch_user = types.MethodType(_fetch_user, bot)
