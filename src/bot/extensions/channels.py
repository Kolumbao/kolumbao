# -*- coding: utf-8 -*-
from typing import Optional
from uuid import uuid4

import discord
from discord.ext import commands
from expiring_dict import ExpiringDict

from ..errors import ItemNotFound
from ..errors import NotManaging
from ..response import bad
from ..response import good
from ..response import resp
from bot.checks import requires_level
from core.db import query
from core.db import session
from core.db.models import Stream
from core.db.models.guild import Guild
from core.db.models.node import Node
from core.db.utils import get_stream
from core.db.utils import get_user
from core.i18n.i18n import _
from core.i18n.i18n import I18n


def get_local_node(stream: Stream, guild: Guild) -> Optional[Node]:
    """Get local node

    Args:
        stream (Stream): Stream
        guild (Guild): Guild

    Returns:
        Optional[Node]: Local node
    """
    return (
        query(Node)
        .filter((Node.stream_id == stream.id) & (Node.guild_id == guild.id))
        .first()
    )


def make_stream_embed(stream: Stream, guild: Optional[Guild] = None) -> discord.Embed:
    description = (
        _("INFO__OFFICIAL_CHANNEL")
        if stream.official
        else _("INFO__UNOFFICIAL_CHANNEL")
    )
    if stream.user.staff:
        description += "\n" + _("INFO__STAFF_CHANNEL")

    if stream.password is not None:
        description += "\n" + _("INFO__LOCKED")

    if guild:
        node = get_local_node(stream, guild)
        if node is not None:
            description += "\n" + _("INFO__INSTALLED", channel_id=node.channel_id)

    embed = discord.Embed(
        title=_("INFO__NAME", stream_name=stream.name),
        description=description or _("NONE"),
    )

    embed.add_field(
        name=_("INFO__DESCRIPTION"), value=stream.description or _("NONE"), inline=False
    )

    embed.add_field(
        name=_("INFO__RULES"), value=stream.rules or _("NONE"), inline=False
    )

    embed.add_field(name=_("INFO__LANGUAGE"), value=stream.language or _("NONE"))
    embed.add_field(name=_("INFO__NSFW"), value=_("YES_") if stream.nsfw else _("NO_"))

    embed.add_field(
        name=_("INFO__STATS"),
        value=f"""
{_('INFO__MESSAGES_TITLE')}: {_('INFO__MESSAGES_CONTENT', amount=stream.message_count)}
{_('INFO__NODES_TITLE')}: {_('INFO__NODES_CONTENT', amount=len(stream.nodes))}
""",
    )

    embed.set_footer(text=_("INFO__INSTALL_WITH", stream_name=stream.name))

    return embed


class Channels(commands.Cog):
    __badge__ = "<:channelsdefault:795415724423118878>"
    __badge_success__ = "<:channelssuccess:795415724410535976>"
    __badge_fail__ = "<:channelsfail:795415724356927498>"

    def __init__(self, bot):
        self.bot = bot
        self._management_dict = ExpiringDict(30 * 60)
        self._delete = ExpiringDict(10)

    def _get_managing(self, ctx) -> Stream:
        """Get the currently managed stream

        Args:
            ctx: The context

        Raises:
            NotManaging: If the user hasn't set a manage command with :func:`.manage`
                or it's expired

        Returns:
            Stream: The stream currently being managed
        """
        stream_id = self._management_dict.get(f"{ctx.author.id}-{ctx.channel.id}")
        if stream_id is not None:
            return query(Stream).get(stream_id)

        raise NotManaging()

    @commands.command()
    async def manage(self, ctx, *, stream_name: str):
        stream = get_stream(stream_name)
        if stream is None:
            raise ItemNotFound(Stream)

        dbuser = get_user(ctx.author.id)
        if stream.user == dbuser or dbuser.has_permissions("MANAGE_STREAMS"):
            self._management_dict[f"{ctx.author.id}-{ctx.channel.id}"] = stream.id
            await good(ctx, _("MANAGE__NOW_MANAGING", stream_name=stream.name))
            self.bot.logger.info("Now managing {}".format(stream.name))
        else:
            await bad(ctx, _("MANAGE__NOT_OWNED"))

    @commands.command()
    async def managing(self, ctx):
        stream = self._get_managing(ctx)
        await good(
            ctx, _("MANAGING__STREAM", stream_name=stream.name, stream_id=stream.id)
        )

    @commands.command("set-name")
    async def name(self, ctx, *, value: str = None):
        stream = self._get_managing(ctx)
        if value is None:
            return await resp(ctx, _("NAME__CURRENT", value=stream.name))

        if get_stream(value) is not None:
            return await bad(ctx, _("NAME__TAKEN"))

        stream.name = value
        session.commit()

        await good(ctx, _("NAME__SET", value=value))
        self.bot.logger.info("Set name to {} for {}".format(value, stream.name))

    @commands.command("set-description")
    async def description_(self, ctx, *, value: str = None):
        stream = self._get_managing(ctx)
        if value is None:
            return await resp(ctx, _("DESCRIPTION__CURRENT", value=stream.description))

        stream.description = value
        session.commit()

        await good(ctx, _("DESCRIPTION__SET", value=value))
        self.bot.logger.info("Set description to {} for {}".format(value, stream.name))

    @commands.command("set-lang")
    async def lang(self, ctx, *, value: str = None):
        stream = self._get_managing(ctx)
        if value is None:
            return await resp(ctx, _("LANG__CURRENT", value=stream.language))

        locale = I18n.get_locale(value)
        if locale is None:
            return await bad(ctx, _("LANG__NOT_FOUND"))

        stream.language = locale
        session.commit()

        await good(ctx, _("LANG__SET", value=value))
        self.bot.logger.info("Set lang to {} for {}".format(value, stream.name))

    @commands.command("set-rules")
    async def rules(self, ctx, *, value: str = None):
        stream = self._get_managing(ctx)
        if value is None:
            return await resp(ctx, _("RULES__CURRENT", value=stream.rules))

        stream.rules = value
        session.commit()

        await good(ctx, _("RULES__SET", value=value))
        self.bot.logger.info("Set rules to {} for {}".format(value, stream.name))

    @commands.command("set-password")
    async def password(self, ctx, *, value: str = None):
        stream = self._get_managing(ctx)
        if value is None:
            stream.set_password()
            session.commit()
            return await resp(ctx, _("PASSWORD__RESET"))

        stream.set_password(value)
        session.commit()

        await good(ctx, _("PASSWORD_SET"))
        self.bot.logger.info(
            "Set password to {} for {}".format(stream.password, stream.name)
        )

    @commands.command("set-nsfw")
    async def nsfw(self, ctx, value: bool = None):
        stream = self._get_managing(ctx)
        if value is None:
            return await resp(ctx, _("NSFW__CURRENT", value=stream.nsfw))

        stream.nsfw = value
        session.commit()

        await good(ctx, _("NSFW__SET", value=value))
        self.bot.logger.info("Set nsfw to {} for {}".format(value, stream.name))

    @requires_level(8)
    @commands.command()
    async def create(self, ctx, *, stream_name: str):
        if get_stream(stream_name) is not None:
            return await bad(ctx, _("NAME__TAKEN"))

        dbuser = get_user(ctx.author.id)
        if len(dbuser.streams) >= 2 and not dbuser.staff:
            return await bad(ctx, _("CREATE__TOO_MANY"))

        stream = Stream(name=stream_name, user=dbuser)

        session.add(stream)
        session.commit()

        await good(ctx, _("CREATE__MADE_GUIDANCE", stream_name=stream.name))

    @commands.command()
    async def delete(self, ctx, code: Optional[str] = None):
        stream = self._get_managing(ctx)
        if code is None:
            self._delete[stream.id] = uuid4().hex
            return await resp(
                ctx, _("DELETE__CONFIRMATION", code=self._delete[stream.id])
            )

        if code == self._delete[stream.id]:
            session.delete(stream)
            session.commit()
            self._management_dict.pop(ctx.author.id + ctx.channel.id)
            return await good(ctx, _("DELETE__SUCCESS"))

        return await bad(ctx, _("DELETE__CODE_INVALID"))


def setup(bot):
    bot.add_cog(Channels(bot))
