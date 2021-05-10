# -*- coding: utf-8 -*-
from typing import Optional

import discord
from discord.ext import commands

from ..checks import has_permission
from ..paginator import EmbedPaginatorSession
from ..response import bad
from ..response import good
from ..response import resp
from core.db import query
from core.db import session
from core.db.models import Node
from core.db.models import OriginMessage
from core.db.models import Snippet
from core.db.utils import get_user
from core.i18n.i18n import _
from core.i18n.i18n import I18n
from core.repeater.converters import Discord


def chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


class Snippets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # bot.event(self.on_command_error)

    @has_permission("MANAGE_SNIPPETS")
    @commands.command("create-snippet")
    async def create_snippet(self, ctx, name: str, *, content: str):
        """Create a snippet"""
        snippet = query(Snippet).filter_by(name=name).first()
        if snippet is not None:
            return await bad(ctx, _("CREATE_SNIPPET__ALREADY_EXISTS"))

        snippet = Snippet(name=name, content=content)
        session.add(snippet)
        session.commit()

        await good(ctx, _("CREATE_SNIPPET__SUCCESS"))
        self.bot.logger.info(f"New snippet `{name}` with content: ```{content}```")

    @has_permission("MANAGE_SNIPPETS")
    @commands.command("delete-snippet")
    async def delete_snippet(self, ctx, name: str):
        """Delete a snippet"""
        snippet = query(Snippet).filter_by(name=name).first()
        if snippet is None:
            return await bad(ctx, _("SNIPPET_NOT_FOUND"))

        session.delete(snippet)
        session.commit()

        await good(ctx, _("DELETE_SNIPPET__SUCCESS"))
        self.bot.logger.info(f"Snippet `{name}` deleted")

    @has_permission("MANAGE_SNIPPETS")
    @commands.command("view-snippet")
    async def view_snippet(self, ctx, name: str):
        """View the details of an individual snippet"""
        snippet = query(Snippet).filter_by(name=name).first()
        if snippet is None:
            return await bad(ctx, _("SNIPPET_NOT_FOUND"))

        await resp(
            ctx,
            _("VIEW_SNIPPET__CONTENT", snippet=snippet.content),
            title=_("VIEW_SNIPPET__TITLE", name=snippet.name),
        )

    @has_permission("MANAGE_SNIPPETS")
    @commands.command("snippets")
    async def snippets(self, ctx):
        """See all available snippets"""
        snippets = query(Snippet).all()

        pages = []
        cks = chunks(snippets, 15)
        for ck in cks:
            embed = discord.Embed(
                title=_("SNIPPETS__TITLE"),
                description="\n".join(
                    f"`{s.name}`: *{s.content[:30]}{'...' if len(s.content) > 30 else ''}*"
                    for s in ck
                ),
            )
            pages.append(embed)

        await EmbedPaginatorSession(ctx, *pages).run()

    def _get_snippet(self, name: str, language: Optional[str] = None) -> Optional[str]:
        suffix = f"-{language}" if language else ""

        snippets_to_search = [
            query(Snippet).filter_by(name=f"{name}{suffix}"),
            query(Snippet).filter_by(name=f"{name}"),
        ]

        for snippet_to_search in snippets_to_search:
            snippet: Snippet = snippet_to_search.first()
            if snippet is not None:
                return snippet

        return None

    @commands.command("send-snippet", aliases=["s"])
    async def send_snippet(self, ctx, name: str, language: Optional[str] = None):
        """Send a snippet across Kolumbao"""
        snippet = self._get_snippet(name, language)

        if snippet is None:
            return

        node = query(Node).filter(Node.channel_id == ctx.channel.id).first()
        user = get_user(ctx.author.id)
        if node is not None and not node.disabled and not user.is_muted():
            session.commit()

            if "AUTOMOD_THIBAULT" in node.stream.features:
                # Check filters
                await Discord.check_filters(
                    user, ctx.message, node.stream.suppressed_filters()
                )

                # Build fake params
                params = {
                    "username": "Thibault",
                    "avatar_url": "https://i.discord.fr/kdE.png",
                    "content": snippet.content,
                    "files": [],
                }
            else:
                params = await Discord.transform(ctx.message, node.stream)
                params["content"] = snippet.content
                params["username"] = Discord.prepare_username(
                    ctx.author.name, ctx.author.discriminator, user.emojis + ["📃"]
                )

            original = OriginMessage(
                user_id=user.id,
                message_id=ctx.message.id,
                node_id=node.id,
                stream_id=node.stream_id,
            )

            session.add(original)
            session.commit()
            await self.bot.client.send(
                params, origin=original, target=node.stream, exclude_origin=False
            )
        else:
            await ctx.send(snippet.content)

    @commands.command()
    async def explanation(self, ctx):
        await self.send_snippet(ctx, "explanation", I18n.get_current_locale())

    @commands.command()
    async def rules(self, ctx):
        await self.send_snippet(ctx, "rules", I18n.get_current_locale())


def setup(bot):
    bot.add_cog(Snippets(bot))
