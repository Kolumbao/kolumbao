# -*- coding: utf-8 -*-
import math
import random
import typing as t
from inspect import cleandoc

import discord
from discord.ext import commands
from expiring_dict import ExpiringDict

from ..paginator import EmbedPaginatorSession
from ..response import bad
from ..response import good
from core.db import query
from core.db import session
from core.db.models import Node
from core.db.models import OriginMessage
from core.db.models.user import User
from core.db.utils import get_user
from core.i18n.i18n import _
from core.i18n.i18n import I18n
from core.logs.log import GlobalDiscordHandler
from core.repeater.converters import Discord


class Users(commands.Cog):
    __badge__ = "<:userdefault:783408212665696266>"
    __badge_success__ = "<:usersuccess:783408212653244476>"
    __badge_fail__ = "<:userfail:783408212778942494>"

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._points_dict = ExpiringDict(120)

    @commands.command()
    async def language(self, ctx, *, language: str = None):
        """Set your preferred language"""
        locale = I18n.get_locale(language)
        if locale is None:
            languages = ", ".join(f"{lang[0]} (`{lang[1]}`)" for lang in I18n.locales)
            return await bad(
                ctx, _("LANGUAGE__NOT_FOUND", name=language, languages=languages)
            )

        get_user(ctx.author.id).language = locale
        I18n.set_current_locale(locale)
        session.commit()

        await good(ctx, _("LANGUAGE__UPDATED"))
        self.bot.logger.debug(f"Set language to {language}")

    def _format_user_badges(self, dbuser):
        content = ""
        if dbuser.staff:
            content += f"{_('USER_STAFF_NOTICE')}\n"

        if len(dbuser.permissions) > 0:
            content += f"{_('USER_ELEVATED_PERMISSIONS')}\n"
        return content

    @commands.command()
    async def profile(self, ctx, *, user: t.Union[discord.User, str] = ""):
        """See a user's profile"""
        if user == "":
            user = ctx.author
        elif isinstance(user, str):
            raise commands.UserNotFound(user)

        dbuser = get_user(user.id)
        content = self._format_user_badges(dbuser)
        if content != "":
            content += "\n"

        mutual_guilds = filter(lambda g: g.get_member(user.id), self.bot.guilds)
        guild_list = ", ".join(map(lambda g: f"{g.name} (`{g.id}`)", mutual_guilds))

        last_seen = _("PROFILE__LAST_SEEN_NEVER")
        q = (
            query(OriginMessage)
            .order_by(OriginMessage.id.desc())
            .filter(OriginMessage.user_id == dbuser.id)
        )
        m = q.first()
        if m is not None:
            last_seen = str(m.sent_at)

        content += cleandoc(
            f"""
            **<:profile:783410236076851252> {_('PROFILE__BASIC_INFO')}**

            **{_('PROFILE__PROFILE')}:** {user.mention}
            **{_('PROFILE__ID')}:** {user.id}
            **{_('PROFILE__MUTUAL')}:** {guild_list}

            **<:stats:783411298318549082> {_('PROFILE__KOLUMBAO_INFO')}**

            **{_('PROFILE__ROLES')}:** {', '.join(map(str,dbuser.roles))}
            **{_('PROFILE__LAST_SEEN')}:** {last_seen}
            **{_('PROFILE__NUMBER_MESSAGES')}:** {q.count()}
            **{_('PROFILE__POINTS')}:** {dbuser.points}
            """
        )

        embed = discord.Embed(
            title=str(user), description=content, colour=discord.Colour.invisible()
        )
        embed.set_thumbnail(url=str(user.avatar_url_as()))

        await ctx.send(embed=embed)

    async def _get_context(
        self, message: discord.Message
    ) -> t.Optional[commands.Context]:
        if message.author.id in self._points_dict:
            return None

        if message.author.bot:
            return None

        if message.content.startswith(("]", "#", "kb!")):
            return None

        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return ctx

    def _add_message_points(self, user: User) -> bool:
        old_level = user.level
        user.points += 10 + random.randint(0, 15)
        session.commit()

        self._points_dict[user.discord_id] = None

        return old_level != user.level

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        ctx = await self._get_context(message)
        if ctx is None:
            return

        # For logging purposes
        GlobalDiscordHandler.set_current_ctx(ctx)

        node = query(Node).filter(Node.channel_id == message.channel.id).first()
        if node is not None and not node.disabled:
            user = get_user(message.author.id)
            passes_filters = await Discord.passes_filters(
                user,
                ctx.message,
                node.stream,
            )
            if not passes_filters:
                return

            # Set locale for message
            I18n.set_current_locale(user.language)

            prev_points = user.points
            is_new_level = self._add_message_points(user)

            if is_new_level:
                # Build fake params
                await self.bot.client.send_art(
                    _("POINTS__LEVEL_UP", level=user.level, user=str(message.author)),
                    node.stream,
                )

            if prev_points == 0:
                await self.bot.client.send_art(
                    _("POINTS__WELCOME", user=str(message.author)), node.stream
                )

    @commands.command()
    async def points(self, ctx, *, user: t.Union[discord.User, str] = ""):
        """Get your current points"""
        if user == "":
            user = ctx.author
        elif isinstance(user, str):
            raise commands.UserNotFound(user)
        dbuser = get_user(user.id)

        amount, total = dbuser.points_to_next_level
        percentage = amount / total * 100
        progress = self.percentage_to_progress(percentage)

        pg_text = f" **`{progress}`** (`{amount}`/`{total}`)"

        embed = discord.Embed(
            title=discord.Embed.Empty,
            description=discord.Embed.Empty,
            color=discord.Color(0x36393F),
        )

        embed.add_field(name=_("POINTS__LEVEL"), value=dbuser.level)
        embed.add_field(name=_("POINTS__AMOUNT"), value=dbuser.points)
        embed.add_field(name="\u2800", value=pg_text, inline=False)

        await ctx.send(embed=embed)

    @commands.command()
    async def leaderboard(self, ctx):  # TODO: laundmo # noqa
        pages = []
        users = query(User).order_by(User.points.desc()).limit(50).all()

        page = []
        last_points = -1
        last_u = -1
        async with ctx.typing():
            for u, user in enumerate(users):
                disc = self.bot.get_user(user.discord_id) or await self.bot.fetch_user(
                    user.discord_id
                )

                pre = " "
                p_u = u
                if last_points == user.points:
                    pre = "="
                    p_u = last_u
                else:
                    last_points = user.points
                    last_u = p_u

                if disc is None:
                    page.append(
                        "`{}{: >2}.` **Unknown user** - level {}".format(
                            pre, p_u + 1, user.level
                        )
                    )
                else:
                    page.append(
                        "`{}{: >2}.` **{}** - level {}".format(
                            pre, p_u + 1, disc, user.level
                        )
                    )

                if (u + 1) % 10 == 0:
                    embed = discord.Embed(
                        title=_("LEADERBOARD__TITLE"), description="\n".join(page)
                    )
                    pages.append(embed)
                    page = []

            if len(page) > 0:
                embed = discord.Embed(
                    title=_("LEADERBOARD__TITLE"), description="\n".join(page)
                )
                pages.append(embed)

            pg = EmbedPaginatorSession(ctx, *pages)
        await pg.run()

    @staticmethod
    def percentage_to_progress(percentage: float):
        markers = ["⣀", "⣄", "⣤", "⣦", "⣶", "⣷", "⣿"]

        # 6 markers for 10
        r = 6 / 10
        s = ""
        for x in range(0, 100, 10):
            over = percentage - x
            if over >= 10:
                s += markers[-1]
            elif over < 0:
                s += markers[0]
            else:
                s += markers[math.floor(over * r)]

        return s


def setup(bot):
    bot.add_cog(Users(bot))
