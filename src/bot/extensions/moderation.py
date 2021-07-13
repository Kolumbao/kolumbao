import asyncio
from datetime import datetime, timedelta
from operator import attrgetter
from os import getenv
from typing import Any, List, Optional, Tuple, TypeVar, Union

import discord
from discord.errors import Forbidden, HTTPException
import pytz
from bot.checks import has_permission
from bot.converters import DurationConverter
from bot.errors import ItemNotFound
from bot.format import format_time, format_user
from bot.response import bad, good, raw_resp
from bot.utils import find_target
from core.db.database import query, session
from core.db.models.guild import Guild, StatusCode
from core.db.models.infraction import Ban, BanSeverity, Mute, Warn
from core.db.models.stream import Stream
from core.db.models.user import User
from core.i18n.i18n import _
from core.repeater.converters import Discord
from discord.ext import commands, tasks
from discord.utils import sleep_until

T = TypeVar("T")


class ModerationNotifier:
    def __init__(self, bot: commands.Bot, model) -> None:
        self.bot = bot
        self.tasks = {}
        self.model = model
        if not hasattr(self.model, "end_time"):
            raise TypeError("Model does not have end time value, which is required")
        if not hasattr(self.model, "user"):
            raise TypeError("Model does not have user value, which is required")

        self.notification_loop.start()

    @property
    def name(self):
        return self.model.__name__.lower()

    async def queue(self, obj, notify_start: bool = True):
        """
        Queue a new object of the model, and send them a message

        Parameters
        ----------
        obj : Any
            The object
        notify_start : bool, optional
            Whether to send a message marking the start, by default True

        Returns
        -------
        asyncio.Task
            The task in charge of this
        """
        if notify_start and obj.user.discord:
            await obj.user.discord.send(
                _("INFRACTION__START", name=self.name, reason=obj.reason, locale=obj.user.language)
            )

        return self.create_end_task(obj)

    @tasks.loop(hours=1)
    async def notification_loop(self):
        # Get all objects that end in less than an hour
        instances = query(self.model).filter(
            (self.model.end_time > datetime.now(pytz.utc))
            & (self.model.end_time < (datetime.now(pytz.utc) + timedelta(hours=1)))
        )

        for obj in instances:
            if obj.id not in self.tasks:
                self.create_end_task(obj)

    async def end_delay(self, obj):
        """
        Sleep until the mute/ban's end time then send the ending message

        Parameters
        ----------
        obj : Any
            The mute/ban
        """
        await sleep_until(obj.end_time)
        await self.end(obj)

    def create_end_task(self, obj):
        if obj.end_time is None or obj.end_time > (
            datetime.now(pytz.utc) + timedelta(hours=1)
        ):
            return

        self.tasks[obj.id] = self.bot.loop.create_task(self.end_delay(obj))
        return self.tasks[obj.id]

    async def requeue(self, obj):
        """
        End a end task prematurely and create a new task with the new
        end time. This can be used if a user is unmuted early.

        Parameters
        ----------
        obj : Any
            The infraction
        """
        # Cancel any pre-existing task
        if obj.id in self.tasks:
            self.tasks[obj.id].cancel()

        # Create new task
        self.create_end_task(obj)

    async def end(self, obj):
        """
        Send a message to the user and delete the task

        Parameters
        ----------
        obj : Any
            The mute/ban
        """
        await obj.user.discord.send(
            _(
                "INFRACTION__END",
                name=self.name,
                start=format_time(obj.start_time),
                reason=obj.reason,
                locale=obj.user.language,
            )
        )

        del self.tasks[obj.id]


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
        self._ensure_banned.start()

        # Sending messages
        self.mute_manage = ModerationNotifier(bot, Mute)
        self.ban_manage = ModerationNotifier(bot, Ban)

    async def log_infraction(self, inf: Union[Mute, Warn, Ban]):
        """Log the creation of an infraction. Does this regardless of actual
        creation time

        Args:
            inf (Infraction): The infraction
        """
        is_severe = isinstance(inf, (Mute, Ban))
        embed = discord.Embed(
            title=f"`{inf.__class__.__name__}` added",
            description=f"#{inf.id} added",
            colour=discord.Colour.red() if is_severe else discord.Colour.orange(),
        )

        # ADd details
        moderator = inf.mod.discord
        user = inf.user.discord
        embed.add_field(name="Moderator", value=f"{moderator} ({inf.mod.discord_id})")
        embed.add_field(name="User", value=f"{user} ({inf.user.discord_id})")
        embed.add_field(name="Reason", value=inf.reason)

        if hasattr(inf, "end_time"):
            if inf.end_time is not None:
                embed.set_footer(text="Ends at")
                embed.timestamp = inf.end_time
            else:
                embed.set_footer(text="Never ends")

        await self.channel.send(embed=embed)

    async def log_end(
        self, inf: Union[Mute, Warn, Ban], intended_end: Optional[datetime] = None
    ):
        """Log the end of an infraction. Does this regardless of actual
        end time.

        Args:
            inf (Infraction): The infraction to log the end of
            intended_end (datetime, optional): The 'intended' end. Defaults to None.
                If this infraction is ended earlier than planned, this should
                be the datetime that was the original end time of
                the given infraction.
        """
        embed = discord.Embed(
            title=f"`{inf.__class__.__name__}` ended",
            description=f"#{inf.id} ended",
            colour=discord.Colour.green(),
        )

        if intended_end:
            embed.set_footer(text="Ended prematurely. Intended end")
            embed.timestamp = intended_end

        await self.channel.send(embed=embed)

    def _find_of_model(
        self, model: T, search: Union[discord.User, timedelta, str]
    ) -> Tuple[List[T], str]:
        found = []
        body = ""
        if isinstance(search, discord.User):
            body = _("SEARCH_INF__BY_USER", user_id=search.id)
            duser = User.create(search)
            infs = (
                query(model)
                .filter((model.mod_id == duser.id) | (model.user_id == duser.id))
                .all()
            )

            found.extend(infs)
        elif isinstance(search, timedelta) and hasattr(model, "start_time"):
            body = _("SEARCH_INF__BY_DURATION", duration=search)
            # 2 hour range
            infs = (
                query(model)
                .filter(
                    (model.end_time - model.start_time < search + timedelta(hours=1))
                    & (model.end_time - model.start_time > search - timedelta(hours=1))
                )
                .all()
            )

            found.extend(infs)
        elif isinstance(search, str):
            body = _("SEARCH_INF__BY_REASON", reason=search)
            infs = query(model).filter(model.reason.contains(search)).all()

            found.extend(infs)

        return found, body

    async def _search(
        self,
        model: Any,
        ctx: commands.Context,
        search: Union[DurationConverter, discord.User, int, str],
    ):
        found, body = self._find_of_model(model, search)

        if len(found) == 0:
            return await bad(ctx, _("SEARCH_INF__NO_RESULTS"))

        embed = discord.Embed(
            title=_("SEARCH_INF__TITLE"),
            description=body,
            colour=discord.Colour.invisible(),
        )

        found.sort(key=attrgetter("id"), reverse=True)
        if len(found) > 6:
            embed.set_footer(text=_("SEARCH_INF__FIRST_N", n=6, tot=len(found)))
            found = found[:6]

        for inf in found:
            u = self.bot.get_user(inf.user.discord_id)
            embed.add_field(
                name=f"#{inf.id} for {format_user(u)}", value=inf.reason, inline=False
            )

        await ctx.send(embed=embed)

    @has_permission("MANAGE_MUTES")
    @commands.group("mute", invoke_without_command=True)
    async def mute(
        self,
        ctx: commands.Context,
        user: discord.User,
        duration: Optional[DurationConverter] = None,
        *,
        reason: Optional[str] = None,
    ):
        if ctx.invoked_subcommand is None:
            dbuser = User.create(user)

            # If already muted, don't mute again
            if dbuser.is_muted():
                return await bad(
                    ctx, _("MUTE__ALREADY_MUTED", mute_id=dbuser.last_mute().id)
                )

            # Create mute
            mute = Mute.create(dbuser, User.create(ctx.author), reason, duration)

            # Add to database
            session.add(mute)
            session.commit()

            await good(ctx, _("MUTE__ADDED", inf_id=mute.id))
            await self.log_infraction(mute)
            await self.mute_manage.queue(mute)

    @has_permission("MANAGE_MUTES")
    @commands.command()
    async def unmute(
        self,
        ctx: commands.Context,
        user: discord.User,
    ):
        dbuser = User.create(user)

        # If not muted, don't unmute
        if not dbuser.is_muted():
            return await bad(ctx, _("MUTE__NOT_MUTED"))

        last_mute = dbuser.last_mute()
        intended_end = last_mute.end_time
        last_mute.end_time = datetime.now(pytz.utc)

        # Add to database
        session.commit()

        await self.log_end(last_mute, intended_end)
        await self.mute_manage.requeue(last_mute)
        await good(ctx, _("UNMUTE__SUCCESS", inf_id=last_mute.id))

    @has_permission("MANAGE_MUTES")
    @commands.group("warn", invoke_without_command=True)
    async def warn(
        self,
        ctx: commands.Context,
        user: discord.User,
        *,
        reason: Optional[str] = None,
    ):
        if ctx.invoked_subcommand is None:
            dbuser = User.create(user)

            # Create warn
            warn = Warn.create(
                dbuser,
                User.create(ctx.author),
                reason,
            )

            # Add to database
            session.add(warn)
            session.commit()

            await self.log_infraction(warn)
            await good(ctx, _("WARN__ADDED", inf_id=warn.id))
            try:
                await warn.user.discord.send(_("WARN__MESSAGE", reason=reason))
            except (AttributeError, Forbidden, HTTPException):
                pass

    @has_permission("MANAGE_MUTES")
    @commands.group("ban", invoke_without_command=True)
    async def ban(
        self,
        ctx: commands.Context,
        user: discord.User,
        duration: Optional[DurationConverter] = None,
        severity: Optional[Union[int, str]] = BanSeverity.USER,
        *,
        reason: Optional[str] = None,
    ):
        if ctx.invoked_subcommand is None:
            dbuser = User.create(user)

            if dbuser.is_banned():
                return await bad(
                    ctx, _("BAN__ALREADY_BANNED", mute_id=dbuser.last_ban().id)
                )

            if isinstance(severity, str):
                if hasattr(BanSeverity, severity.upper()):
                    severity = getattr(BanSeverity, severity.upper())
                else:
                    return await bad(ctx, _("BAN__SEVERITY_UNKNOWN"))

            # Create warn
            ban = Ban.create(
                dbuser, User.create(ctx.author), reason, severity, duration
            )

            # Add to database
            session.add(ban)
            session.commit()

            await self.log_infraction(ban)
            await self.ban_manage.queue(ban)
            await good(ctx, _("BAN__ADDED", inf_id=ban.id))

    @has_permission("MANAGE_MUTES")
    @commands.command()
    async def unban(
        self,
        ctx: commands.Context,
        user: discord.User,
    ):
        dbuser = User.create(user)

        # If not muted, don't unmute
        if not dbuser.is_banned():
            return await bad(ctx, _("BAN__NOT_BANNED"))

        last_ban = dbuser.last_ban()
        intended_end = last_ban.end_time
        last_ban.end_time = datetime.now(pytz.utc)

        # Add to database
        session.commit()

        await good(ctx, _("UNBAN__SUCCESS", inf_id=last_ban.id))
        await self.log_end(last_ban, intended_end)
        await self.ban_manage.requeue(last_ban)


    @has_permission("MANAGE_MUTES")
    @commands.command("server-ban")
    async def server_ban(
        self,
        ctx: commands.Context,
        guild_id: int,
        *,
        reason: Optional[str] = None,
    ):
        dbguild = Guild.create(discord.Object(guild_id))
        if dbguild.disabled:
            # Create warn
            return await bad(ctx, _("SERVER_BAN__BANNED"))
        
        dbguild.status = StatusCode.MANUALLY_DISABLED
        session.commit()

        await good(ctx, _("SERVER_BAN__ADDED"))
        target = find_target(dbguild.discord)
        await target.send(_("SERVER_BAN__BANNED_FOR", reason=reason))

    @has_permission("MANAGE_MUTES")
    @commands.command("server-unban")
    async def server_unban(
        self,
        ctx: commands.Context,
        guild_id: int
    ):
        dbguild = Guild.create(discord.Object(guild_id))
        if not dbguild.disabled:
            # Create warn
            return await bad(ctx, _("SERVER_BAN__NOT_BANNED"))
        
        dbguild.status = StatusCode.NONE
        session.commit()

        await good(ctx, _("SERVER_BAN__UNBANNED"))
        
        target = find_target(dbguild.discord)
        await target.send(_("SERVER_BAN__UNBANNED"))

    # Search commands
    @mute.command("search")
    async def mute__search(
        self, ctx, *, search: Union[DurationConverter, discord.User, int, str]
    ):
        await self._search(Mute, ctx, search)

    @ban.command("search")
    async def ban__search(self, ctx, *, search: Union[discord.User, int, str]):
        await self._search(Ban, ctx, search)

    @warn.command("search")
    async def warn__search(self, ctx, *, search: Union[discord.User, int, str]):
        await self._search(Warn, ctx, search)

    @has_permission("MANAGE_LOCKDOWN")
    @commands.command("lockdown")
    async def lockdown(
        self, ctx, stream_name: str, type_: str, value: Optional[int] = 5
    ):
        stream = Stream.create(stream_name)
        if stream is None:
            raise ItemNotFound(Stream)

        if type_ == "full":
            stream.lockdown = 999
            text = _(
                "LOCKDOWN__FULL",
                stream=stream.name,
                locale=stream.language,
            )
        elif type_ == "level":
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

    @tasks.loop(minutes=30)
    async def _ensure_banned(self):
        self.bot.logger.info(
            "Auditing all guilds to ensure banned members are not on servers"
        )
        # Get members
        query_result = await self.bot.loop.run_in_executor(None,
            query(Ban)
            .filter(
                ((Ban.end_time == None) | (Ban.end_time > datetime.now(pytz.utc)))
                & (Ban.severity == BanSeverity.BLANKET)
            )
            .all
        )

        banned_users = set(map(lambda b: b.user.discord, query_result))

        # Check guilds that aren't already banned
        for dbguild in await self.bot.loop.run_in_executor(None, (
            query(Guild)
            .filter(
                (Guild.status == StatusCode.NONE)
                | (Guild.status == StatusCode.AWAITING_DISABLE)
            )
            .all
        )):
            # Await to give control to event loop!
            await asyncio.sleep(0.001)
            
            if dbguild.discord:
                target = find_target(dbguild.discord)
                members = set(dbguild.discord.members)

                # Get intersection
                banned_users_in_guild = list(banned_users.intersection(members))
                if len(banned_users_in_guild) > 0:
                    if dbguild.status == StatusCode.NONE:
                        # Disable
                        dbguild.status = StatusCode.AWAITING_DISABLE
                        session.commit()

                        await self.send_user_warning_to_guild(
                            dbguild, banned_users_in_guild
                        )
                    elif dbguild.status == StatusCode.AWAITING_DISABLE:
                        dbguild.status = StatusCode.DISABLED
                        await target.send(_("GUILD__BANNED_USER"))
                elif dbguild.status != StatusCode.NONE:
                    dbguild.status = StatusCode.NONE
                    await target.send(_("GUILD__NO_LONGER_BANNED"))

                session.commit()

    async def send_user_warning_to_guild(
        self, dbguild: Guild, banned_users_in_guild: list
    ):
        self.bot.logger.info(
            f"Guild {dbguild.discord} ({dbguild.discord_id}) has received a"
            f"warning for users: {list(map(str, banned_users_in_guild))}"
        )
        await find_target(dbguild.discord).send(
            _(
                "GUILD__WARNING_BANNED_USERS_PRESENT",
                users=", ".join(map(str, banned_users_in_guild)),
            )
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        dbuser = User.create(member)
        if dbuser.is_banned():
            if dbuser.last_ban().severity == BanSeverity.BLANKET:
                dbguild = Guild.create(member.guild)

                # Set to warning
                dbguild.status = StatusCode.AWAITING_DISABLE
                session.commit()

                if dbguild.discord:
                    await self.send_user_warning_to_guild(dbguild, [member])


def setup(bot: commands.Bot):
    bot.add_cog(Moderation(bot))
