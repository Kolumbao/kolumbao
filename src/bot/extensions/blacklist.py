# -*- coding: utf-8 -*-
import discord
from discord.ext import commands

from ..checks import has_permission
from bot.paginator import EmbedPaginatorSession
from bot.response import bad
from bot.response import good
from bot.response import resp
from core.db import session
from core.db.database import query
from core.db.models.blacklist import Blacklist
from core.db.utils import get_blacklist
from core.i18n.i18n import _


def chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


class BlacklistManager(commands.Cog):
    __badge__ = "<:blacklistdefault:795413375231852584>"
    __badge_success__ = "<:blacklistsuccess:795413375264751616>"
    __badge_fail__ = "<:blacklistfail:795413375336185916>"

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @has_permission("MANAGE_BLACKLISTS")
    @commands.command("create-blacklist")
    async def create_blacklist(self, ctx, name: str, *, value: str):
        """Create a new blacklist (regex)"""
        if get_blacklist(name) is not None:
            return await bad(ctx, _("CREATE_BLACKLIST__ALREADY_EXISTS"))

        blacklist = Blacklist(name=name, value=value)
        session.add(blacklist)
        session.commit()

        await good(ctx, _("CREATE_BLACKLIST__SUCCESS"))
        self.bot.logger.info(f"New blacklist `{name}` with content: ```{value}```")

    @has_permission("MANAGE_BLACKLISTS")
    @commands.command("delete-blacklist")
    async def delete_blacklist(self, ctx, name: str):
        """Delete a blacklist"""
        blacklist = get_blacklist(name)
        if blacklist is None:
            return await bad(ctx, _("BLACKLIST_NOT_FOUND"))

        session.delete(blacklist)
        session.commit()

        await good(ctx, _("DELETE_BLACKLIST__SUCCESS"))
        self.bot.logger.info(f"Blacklist `{name}` deleted")

    @has_permission("MANAGE_BLACKLISTS")
    @commands.command("view-blacklist")
    async def view_blacklist(self, ctx, name: str):
        """View a specific blacklist"""
        blacklist = get_blacklist(name)
        if blacklist is None:
            return await bad(ctx, _("BLACKLIST_NOT_FOUND"))

        await resp(
            ctx,
            _("VIEW_BLACKLIST__CONTENT", blacklist=blacklist.value),
            title=_("VIEW_BLACKLIST__TITLE", name=blacklist.name),
        )

    @has_permission("MANAGE_BLACKLISTS")
    @commands.command("blacklists")
    async def blacklists(self, ctx):
        """See a list of all blacklists"""
        blacklists = query(Blacklist).all()

        pages = []
        cks = chunks(blacklists, 15)
        for ck in cks:
            embed = discord.Embed(
                title=_("BLACKLISTS__TITLE"),
                description="\n".join(
                    f"`{s.name}`: *{s.value[:30]}{'...' if len(s.value) > 30 else ''}*"
                    for s in ck
                ),
            )
            pages.append(embed)

        await EmbedPaginatorSession(ctx, *pages).run()


def setup(bot):
    bot.add_cog(BlacklistManager(bot))
