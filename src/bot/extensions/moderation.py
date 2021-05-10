# -*- coding: utf-8 -*-
from datetime import datetime
from datetime import timedelta
from operator import attrgetter
from os import getenv
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union

import discord
from discord.ext import commands

from ..response import bad
from ..response import good
from ..response import raw_resp
from bot.checks import has_permission
from bot.converters import DurationConverter
from bot.errors import ItemNotFound
from bot.format_time import format_time
from bot.format_time import format_user
from core.db.database import query
from core.db.database import session
from core.db.models.infraction import Infraction
from core.db.models.stream import Stream
from core.db.utils import get_stream
from core.db.utils import get_user
from core.i18n.i18n import _
from core.moderation.infraction import add_mute
from core.moderation.infraction import add_warning
from core.repeater.converters import Discord


class ConversionError(TypeError):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__()


class Moderation(commands.Cog):
    __badge__ = "<:moderationdefault:795414665416278046>"
    __badge_success__ = "<:moderationsuccess:795414701306806282>"
    __badge_fail__ = "<:moderationfail:795414701310869554>"

    def __init__(self, bot: commands.Bot) -> None:
        """Create a moderation cog

        Args:
            bot (commands.Bot): Bot
        """
        self.bot = bot
        self.channel = self.bot.get_channel(int(getenv("INFRACTION_LOG")))

    def _find_infractions(self, search) -> Tuple[List[Infraction], str]:
        found = []
        body = ""
        if isinstance(search, discord.User):
            body = _("SEARCH_INF__BY_USER", user_id=search.id)
            duser = get_user(search.id)
            infs = (
                query(Infraction)
                .filter(
                    (Infraction.mod_id == duser.id) | (Infraction.user_id == duser.id)
                )
                .all()
            )

            found.extend(infs)
        elif isinstance(search, timedelta):
            body = _("SEARCH_INF__BY_DURATION", duration=search)
            # 2 hour range
            infs = (
                query(Infraction)
                .filter(
                    (
                        Infraction.end_time - Infraction.start_time
                        < search + timedelta(hours=1)
                    )
                    & (
                        Infraction.end_time - Infraction.start_time
                        > search - timedelta(hours=1)
                    )
                )
                .all()
            )

            found.extend(infs)
        elif isinstance(search, str):
            body = _("SEARCH_INF__BY_REASON", reason=search)
            infs = query(Infraction).filter(Infraction.reason.contains(search)).all()

            found.extend(infs)

        return found, body

    async def log_infraction(self, inf: Infraction):
        """Log the creation of an infraction. Does this regardless of actual
        creation time

        Args:
            inf (Infraction): The infraction
        """
        is_mute = inf.type_ == "mute"
        embed = discord.Embed(
            title=f"`{inf.type_}` added",
            description=f"New infraction #{inf.id} added",
            colour=discord.Colour.red() if is_mute else discord.Colour.orange(),
        )

        moderator = self.bot.get_user(inf.mod.discord_id)
        user = self.bot.get_user(inf.user.discord_id)
        embed.add_field(name="Moderator", value=f"{moderator} ({inf.mod.discord_id})")
        embed.add_field(name="User", value=f"{user} ({inf.user.discord_id})")
        embed.add_field(name="Reason", value=inf.reason)

        if inf.end_time is not None:
            embed.set_footer(text="Ends at")
            embed.timestamp = inf.end_time
        else:
            embed.set_footer(text="Never ends")

        await self.channel.send(embed=embed)

    async def log_end(self, inf: Infraction, intended_end: Optional[datetime] = None):
        """Log the end of an infraction. Does this regardless of actual
        end time

        Args:
            inf (Infraction): The infraction to log the end of
            intended_end (datetime, optional): The 'intended' end. Defaults to None.
                If this infraction is ended earlier than planned, this should
                be the datetime that was the original end time of
                the given infraction.
        """
        embed = discord.Embed(
            title=f"`{inf.type_}` ended",
            description=f"Infraction #{inf.id} ended",
            colour=discord.Colour.green(),
        )

        if intended_end:
            embed.set_footer(text="Ended prematurely. Intended end")
            embed.timestamp = intended_end

        await self.channel.send(embed=embed)

    @staticmethod
    def _warn(
        moderator: discord.User,
        user: discord.User,
        duration: Optional[timedelta] = None,
        reason: Optional[str] = None,
    ) -> Infraction:
        """Create an infraction of type ``warning`` given a duration.

        Args:
            moderator (discord.User): The moderator that initiated the infraction
            user (discord.User): The user the infraction targets
            duration (timedelta, optional): The duration. Defaults to None.
                If the duration is given as ``None``, it is an 'infinite'
                infraction.
            reason (str, optional): The reason. Defaults to None.

        Returns:
            Infraction: The created infraction.
        """
        end_time = datetime.now() + duration if duration else None
        return add_warning(get_user(moderator.id), get_user(user.id), end_time, reason)

    @staticmethod
    def _mute(
        moderator: discord.User,
        user: discord.User,
        duration: Optional[timedelta] = None,
        reason: Optional[str] = None,
    ) -> Infraction:
        """Create an infraction of type ``mute`` given a duration.

        Args:
            moderator (discord.User): The moderator that initiated the infraction
            user (discord.User): The user the infraction targets
            duration (timedelta, optional): The duration. Defaults to None.
                If the duration is given as ``None``, it is an 'infinite'
                infraction.
            reason (str, optional): The reason. Defaults to None.

        Returns:
            Infraction: The created infraction.
        """
        end_time = datetime.now() + duration if duration else None
        return add_mute(get_user(moderator.id), get_user(user.id), end_time, reason)

    @has_permission("MANAGE_WARNS")
    @commands.command()
    async def warn(
        self,
        ctx,
        user: discord.User,
        duration: Optional[DurationConverter] = None,
        *,
        reason: Optional[str] = None,
    ):
        """Warn a user"""
        inf = self._warn(ctx.author, user, duration, reason)
        await good(ctx, _("WARN__ADDED", inf_id=inf.id))
        await self.log_infraction(inf)

    @has_permission("MANAGE_MUTES")
    @commands.command()
    async def mute(
        self,
        ctx,
        user: discord.User,
        duration: Optional[DurationConverter] = None,
        *,
        reason: Optional[str] = None,
    ):
        """Mute a user"""
        try:
            inf = self._mute(ctx.author, user, duration, reason)
            session.commit()
        except ValueError:
            await bad(
                ctx, _("MUTE__ALREADY_MUTED", mute_id=get_user(user.id).last_mute().id)
            )
        else:
            await good(ctx, _("MUTE__ADDED", inf_id=inf.id))
            await self.log_infraction(inf)

    @has_permission("MANAGE_MUTES")
    @commands.command()
    async def unmute(self, ctx, user: discord.User):
        """Unmute a user"""
        duser = get_user(user.id)
        if duser.is_muted():
            last_mute = get_user(user.id).last_mute()
            intended_end = last_mute.end_time
            last_mute.end_time = datetime.now()
            session.commit()
            await good(ctx, _("UNMUTE__SUCCESS"))
            await self.log_end(last_mute, intended_end)
        else:
            await bad(ctx, _("UNMUTE__NOT_MUTED"))

    @has_permission("MANAGE_MUTES", "MANAGE_WARNS")
    @commands.group("inf", invoke_without_command=True)
    async def inf(self, ctx, inf_id: int):
        """Display the details of an infraction"""
        if ctx.invoked_subcommand is None:
            inf: Infraction = query(Infraction).get(inf_id)
            if inf is None:
                return await bad(ctx, _("SEARCH_INF__ID_NOT_FOUND", inf_id=inf_id))

            embed = discord.Embed(
                title=f"`{inf.type_}` infraction",
                description=inf.reason,
                colour=discord.Colour.invisible(),
            )

            u = self.bot.get_user(inf.user.discord_id)
            m = self.bot.get_user(inf.mod.discord_id)

            embed.add_field(name=_("INF__ID"), value=inf.id)
            embed.add_field(
                name=_("INF__START_TIME"), value=format_time(inf.start_time)
            )
            embed.add_field(name=_("INF__END_TIME"), value=format_time(inf.end_time))
            embed.add_field(name=_("INF__USER"), value=format_user(u))
            embed.add_field(name=_("INF__MOD"), value=format_user(m))

            await ctx.send(embed=embed)

    @has_permission("MANAGE_MUTES", "MANAGE_WARNS")
    @inf.command("search")
    async def inf__search(
        self, ctx, *, search: Union[DurationConverter, discord.User, int, str]
    ):
        """Search for an infraction

        Args:
            search (duration | user | int | str): The query
        """
        found, body = self._find_infractions(search)

        if len(found) == 0:
            return await bad(ctx, _("SEARCH_INF__NO_RESULTS"))

        embed = discord.Embed(
            title=_("SEARCH_INF__TITLE"),
            description=body,
            colour=discord.Colour.invisible(),
        )

        found.sort(key=attrgetter("start_time"), reverse=True)
        if len(found) > 6:
            embed.set_footer(text=_("SEARCH_INF__FIRST_N", n=6, tot=len(found)))
            found = found[:6]

        for inf in found:
            u = self.bot.get_user(inf.user.discord_id)
            embed.add_field(
                name=f"#{inf.id} for {format_user(u)}", value=inf.reason, inline=False
            )

        await ctx.send(embed=embed)

    def _edit_inf(
        self,
        inf: Infraction,
        field: str,
        new_value: Optional[Union[DurationConverter, str]] = None,
    ):
        if field not in ["duration", "reason"] and new_value is None:
            raise ConversionError("EDIT_INF__CANNOT_SET_FIELD_TO_NONE")

        if isinstance(new_value, (str, timedelta)):
            try:
                setattr(inf, field, new_value)
            except AttributeError:
                raise ConversionError("EDIT_INF__INVALID_FIELD")
            except ValueError as e:
                raise ConversionError(e.args[0])
        else:
            raise ConversionError("EDIT_INF__INVALID_VALUE_FOR_FIELD")

    @has_permission("MANAGE_MUTES", "MANAGE_WARNS")
    @inf.command("edit")
    async def inf__edit(
        self,
        ctx,
        ident: int,
        field: str,
        new_value: Optional[Union[DurationConverter, str]] = None,
    ):
        """Edit an infraction

        Args:
            ident (int): Infraction ID
            field (str): The attribute to change
            new_value (str | duration): The new value (duration for 'end', str otherwise)
        """
        inf: Infraction = query(Infraction).get(ident)
        if inf is None:
            return await bad(ctx, _("EDIT_INF__NOT_FOUND"))
        if field not in ["duration", "reason", "type"]:
            return await bad(ctx, _("EDIT_INF__INVALID_FIELD"))

        try:
            self._edit_inf(inf, field, new_value=new_value)
        except ConversionError as exc:
            return await bad(ctx, _(exc.message))

        session.commit()
        await good(ctx, _("EDIT_INF__SUCCESS", field=field, value=str(new_value)))
        await self.channel.send(
            f"Modification of `#{inf.id}` : **{field}** set to **{new_value}** "
            f"by {ctx.author} ({ctx.author.id})"
        )

    @has_permission("MANAGE_LOCKDOWN")
    @commands.command("lockdown")
    async def lockdown(
        self, ctx, stream_name: str, type_: str, value: Optional[int] = 5
    ):
        stream = get_stream(stream_name)
        if stream is None:
            raise ItemNotFound(Stream)

        if type_ == "level":
            stream.lockdown = -value
            text = _(
                "LOCKDOWN__LEVEL",
                level=value,
                stream=stream.name,
                locale=stream.language,
            )
        elif type_ == "slow":
            stream.lockdown = value
            text = _(
                "LOCKDOWN__SLOWMODE",
                limit=value,
                stream=stream.name,
                locale=stream.language,
            )
        elif type_ == "off":
            stream.lockdown = 0
            text = _(
                "LOCKDOWN__DISACTIVATED", stream=stream.name, locale=stream.language
            )
        else:
            return await bad(ctx, _("LOCKDOWN__INVALID_TYPE"))

        embed = raw_resp(ctx, text)
        embed.set_thumbnail(
            url="https://cdn.discordapp.com/emojis/796755138978643988.png?v=1"
        )
        await self.bot.client.send_art(
            "", stream, embeds=[Discord.prepare_embed(embed)]
        )

        await good(ctx, text)


def setup(bot: commands.Bot):
    bot.add_cog(Moderation(bot))
