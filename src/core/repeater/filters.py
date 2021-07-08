# -*- coding: utf-8 -*-
import re

import discord
from discord.ext import commands
from expiring_dict.expiringdict import ExpiringDict

from core.db.models.guild import Guild

from ..db.models import User
from ..utils.ratelimit import RateLimit
from core.db.database import query
from core.db.models.blacklist import Blacklist
from core.db.models.stream import Stream


class FilterError(ValueError):
    """When a filter fails"""

    def __init__(self, filter_failed, *args, **kwargs):
        self.filter_failed = filter_failed
        super().__init__(*args, **kwargs)


async def _mute_filter(user: User, _, __, ___):
    return not user.is_muted()

async def _ban_filter(user: User, _, __, ___):
    return not user.is_banned()

async def _guild_ban_filter(user: User, message: discord.Message, _, __):
    return not Guild.create(message.guild).disabled

def _is_invite_allowed(invite: discord.Invite):
    # Kolumbao
    if invite.guild.id == 457205628754984960:
        return True

    return any(feat in invite.guild.features for feat in ["PARTNERED", "VERIFIED"])


async def _invite_filter(_, message: discord.Message, bot: commands.Bot, __):
    for match in re.findall(
        r"(?:discord\.(?:gg|io|me|li)|discordapp\.com\/invite)\/.[a-zA-Z0-9]+",
        message.content,
    ):
        try:
            invite = await bot.fetch_invite(match)
        except (discord.NotFound, discord.HTTPException):
            return False
        else:
            if invite.guild is not None and not _is_invite_allowed(invite):
                return False

    return True


_content_ratelimit = RateLimit(limit=4, per=3)


async def _content_ratelimit_filter(_, message: discord.Message, __, ___):
    return not _content_ratelimit.enter(message.content)


_user_ratelimit = RateLimit(limit=6, per=3)


async def _user_ratelimit_filter(_, message: discord.Message, __, ___):
    return not _user_ratelimit.enter(message.author.id)


_stream_ratelimits = ExpiringDict()


async def _lockdown_filter(user: User, _, __, stream: Stream):
    if stream.lockdown == 0:
        return True

    # Full lockdown
    if stream.lockdown == 9999:
        return False

    if stream.lockdown < 0:
        return user.level >= abs(stream.lockdown)

    # Must be > 0
    key = f"{user.id}-{stream.id}"
    if key in _stream_ratelimits:
        return False

    _stream_ratelimits.ttl(key, None, stream.lockdown)
    return True


async def _blacklist_filter(_, message: discord.Message, __, stream: Stream):
    suppressed_filters = stream.suppressed_filters()
    for blacklist in query(Blacklist).all():
        if blacklist.name not in suppressed_filters:
            if re.match(blacklist.value, message.clean_content):
                return False

    return True


FILTERS = {
    "MUTE_FILTER": _mute_filter,
    "BAN_FILTER": _ban_filter,
    "GUILD_BAN_FILTER": _guild_ban_filter,
    "INVITE_FILTER": _invite_filter,
    "CONTENT_RATELIMIT_FILTER": _content_ratelimit_filter,
    "USER_RATELIMIT_FILTER": _user_ratelimit_filter,
    "BLACKLIST_FILTER": _blacklist_filter,
    "LOCKDOWN_FILTER": _lockdown_filter,
}
