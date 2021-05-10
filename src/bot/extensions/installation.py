# -*- coding: utf-8 -*-
import asyncio
from typing import Optional

import discord
import psycopg2
import sqlalchemy
from discord.channel import TextChannel
from discord.errors import Forbidden
from discord.errors import NotFound
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType
from discord.ext.commands.core import bot_has_permissions
from discord.ext.commands.core import cooldown
from discord.ext.commands.core import has_permissions
from discord.utils import oauth_url

from .channels import get_local_node
from .channels import make_stream_embed
from bot.errors import ItemNotFound
from bot.paginator import EmbedPaginatorSession
from bot.response import bad
from bot.response import good
from bot.response import resp
from core.db import session
from core.db.database import query
from core.db.models import Stream
from core.db.models.guild import Guild
from core.db.models.node import Node
from core.db.utils import get_guild
from core.db.utils import get_stream
from core.db.utils import get_user
from core.i18n.i18n import _
from repeater.handlers import StatusCode


class Installation(commands.Cog):
    __badge__ = "<:installationdefault:795413869811990628>"
    __badge_success__ = "<:installationsuccess:795413869727186964>"
    __badge_fail__ = "<:installationfail:795413869677641728>"

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command("all")
    async def all_(self, ctx):
        streams = query(Stream).all()
        streams.sort(key=lambda stream: stream.message_count, reverse=True)

        embeds = []
        for stream in streams:
            embed = make_stream_embed(stream, get_guild(ctx.guild.id))
            embeds.append(embed)

        await EmbedPaginatorSession(ctx, *embeds).run()

    @commands.command()
    async def installed(self, ctx):
        dbguild = get_guild(ctx.guild.id)
        nodes = (
            query(Node)
            .filter(Node.guild_id == dbguild.id)
            .order_by(Node.webhook_id.asc())
            .all()
        )

        embeds = []
        for node in nodes:
            embed = make_stream_embed(node.stream, dbguild)
            embed.title = _("INSTALLED__TITLE") + " | " + embed.title
            embeds.append(embed)

        await EmbedPaginatorSession(ctx, *embeds).run()

    @commands.command()
    async def info(self, ctx, *, stream_name: str):
        stream = get_stream(stream_name)
        if stream is None:
            raise ItemNotFound(Stream)

        embed = make_stream_embed(stream, get_guild(ctx.guild.id))

        await ctx.send(embed=embed)

    async def _join(
        self, channel: discord.TextChannel, stream: Stream, guild: Guild
    ) -> Node:
        """Creates a node and webhook for the given channel.

        This function assumes the permissions have been checked, and does not
        handle any errors from creating the webhook.

        Args:
            channel (discord.TextChannel): The channel to add to
            stream (Stream): The stream to create the node for

        Returns:
            Node: The created node
        """
        webhook = await channel.create_webhook(
            name=f"Webhook for #{stream.name}",
            avatar=await self.bot.user.avatar_url_as().read(),
            reason="Creation of webhook for Kolumbao channel - "
            "**deleting this webhook will disable the channel**",
        )

        node = Node(
            stream=stream,
            guild=guild,
            channel_id=channel.id,
            webhook_id=webhook.id,
            webhook_token=webhook.token,
        )

        session.add(node)
        return node

    @bot_has_permissions(manage_channels=True, manage_webhooks=True)
    @has_permissions(manage_channels=True, manage_webhooks=True)
    @cooldown(1, 60, BucketType.guild)
    @commands.command()
    async def join(  # noqa MC0001
        self, ctx, stream_name: str, channel: Optional[discord.TextChannel] = None
    ):
        """Add a kolumbao channel to your server"""
        overwrites = {
            ctx.guild.me: discord.PermissionOverwrite(
                read_messages=True, send_messages=True, manage_messages=True
            )
        }

        dguild = get_guild(ctx.guild.id)
        async with ctx.typing():
            stream: Stream = query(Stream).filter(Stream.name == stream_name).first()
            if stream is None:
                return await bad(ctx, _("JOIN__NO_STREAM"))

            if stream.password is not None:
                # Check password
                def check(m: discord.Message):
                    return m.author == ctx.author and m.channel == ctx.channel

                await resp(ctx, _("JOIN__ENTER_PASSWORD"))
                try:
                    message = await self.bot.wait_for(
                        "message", check=check, timeout=30
                    )
                    if not stream.check_password(message.content):
                        return await bad(ctx, _("JOIN__PASSWORD_INCORRECT"))
                    await message.delete()
                except asyncio.TimeoutError:
                    return await bad(ctx, _("JOIN__TOO_LONG_TO_RESPOND"))
                except (discord.Forbidden, discord.HTTPException):
                    # Catch errors deleting message
                    pass

                await good(ctx, _("JOIN__PASSWORD_CORRECT"))

            node = get_local_node(stream, dguild)
            if node is not None:
                return await bad(
                    ctx, _("JOIN__ALREADY_JOINED", channel_id=node.channel_id)
                )

            if channel is None:
                channel = await ctx.guild.create_text_channel(
                    stream.name,
                    overwrites=overwrites,
                    nsfw=stream.nsfw,
                    topic=f"Kolumbao connection to #{stream.name} ",
                )
            else:
                overwrites = {**channel.overwrites, **overwrites}

                try:
                    await channel.edit(
                        reason="Kolumbao setup to ensure access", overwrites=overwrites
                    )
                except discord.Forbidden:
                    pass

            session.add(dguild)
            node = await self._join(channel, stream, dguild)
            session.add(node)
            session.commit()

            await good(channel, _("JOIN__SETUP"), badge=self.__badge_success__)
            await good(ctx, _("JOIN__SUCCESS", channel_id=node.channel_id))
            self.bot.logger.info("Created connection to {}".format(stream_name))

    async def _leave(self, stream: Stream, guild: Guild) -> Optional[TextChannel]:
        """Make the bot destroy the node and webhook for a stream on a guild

        Handles discord.errors.NotFound errors from webhook functions
        but not other errors. You should handle these yourself.

        Args:
            stream (Stream): The stream to remove the node for
            guild (Guild): The guild the node exists on

        Raises:
            discord.errors.HTTPException: An discord.errors.HTTPException
                occured when requesting the webhook or deleting it.
            discord.errors.Forbidden: A discord.errors.Forbidden
                occured when requesting the webhook or deleting it.

        Returns:
            Optional[TextChannel]: The channel the node existed on
        """
        node = get_local_node(stream, guild)
        if node is None:
            raise KeyError

        # Try delete the webhook
        try:
            webhook = await self.bot.fetch_webhook(node.webhook_id)
            await webhook.delete()
        except NotFound:
            pass
        except Exception as err:
            raise err

        await self.bot.loop.run_in_executor(None, session.delete, node)
        return self.bot.get_channel(node.channel_id)

    @bot_has_permissions(manage_channels=True, manage_webhooks=True)
    @has_permissions(manage_channels=True, manage_webhooks=True)
    # @cooldown(1, 60, BucketType.guild)
    @commands.command()
    async def leave(self, ctx, stream_name: str):
        """Remove a Kolumbao channel from your server (just gets rid of the connection)"""
        guild = get_guild(ctx.guild.id)
        async with ctx.typing():
            stream = query(Stream).filter(Stream.name == stream_name).first()
            if stream is None:
                return await bad(ctx, _("LEAVE__NO_STREAM"))

            try:
                channel = await self._leave(stream, guild)
                session.commit()
            except Forbidden:
                return await bad(ctx, _("LEAVE__FORBIDDEN"))
            except KeyError:
                return await bad(ctx, _("LEAVE__NOT_INSTALLED"))
            else:
                if channel is not None:
                    await resp(
                        channel, _("LEAVE__DELETE_CHANNEL"), badge=self.__badge__
                    )

            await good(ctx, _("LEAVE__LEFT", channel_id=channel.id))
            self.bot.logger.info("Removed connection to {}".format(stream_name))

    @commands.command()
    async def search(self, ctx, name_query: str):
        streams = query(Stream).all()
        found_streams = []
        for stream in streams:
            if name_query in stream.name:
                found_streams.append(stream)

        if len(found_streams) > 0:
            await EmbedPaginatorSession(
                ctx,
                *[
                    make_stream_embed(stream, get_guild(ctx.guild.id))
                    for stream in found_streams
                ],
            ).run()
        else:
            await bad(ctx, _("SEARCH__NOT_FOUND"))

    @commands.command()
    async def diagnose(self, ctx, stream_name: str):
        stream = query(Stream).filter(Stream.name == stream_name).first()
        if stream is None:
            raise ItemNotFound(Stream)

        node = get_local_node(stream, get_guild(ctx.guild.id))

        error = {
            StatusCode.WEBHOOK_NOT_FOUND.value: _("DIAGNOSE__WEBHOOK_DELETED"),
            StatusCode.WEBHOOK_NOT_AUTHORIZED.value: _("DIAGNOSE__NOT_AUTHORIZED"),
            StatusCode.WEBHOOK_HTTP_EXCEPTION.value: _("DIAGNOSE__OTHER_UNKNOWN"),
        }
        if node.status != 0:
            return await bad(ctx, error[node.status])

        return await good(ctx, _("DIAGNOSE__NO_ERROR"))

    @commands.command(aliases=["link"])
    async def invite(self, ctx):
        url = oauth_url(
            self.bot.user.id,
            permissions=discord.Permissions(
                manage_channels=True,
                manage_webhooks=True,
                view_channel=True,
                read_messages=True,
                send_messages=True,
                manage_messages=True,
                embed_links=True,
                external_emojis=True,
            ),
        )
        embed = discord.Embed(
            title=_("INVITE__TITLE"),
            description=_("INVITE__CONTENT", url=url),
            color=discord.Colour.invisible(),
        )
        await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        dbguild = get_guild(guild.id)
        session.commit()

        self.bot.logger.info(
            "{0.name} ({0.id}) added the bot ({1})".format(guild, dbguild.id)
        )
        language = get_user(guild.owner_id).language

        target = None

        # Find a channel I can talk in
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                target = channel
                break

        if target is None:
            # TODO: Contact the owner
            target = guild.owner

        if target is None:
            return

        await target.send(_("INSTALLED", locale=language))

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        dbguild = get_guild(guild.id)
        session.commit()
        self.bot.logger.info(
            "{0.name} ({0.id}) kicked the bot ({1})".format(guild, dbguild.id)
        )

        try:
            session.delete(dbguild)
        except sqlalchemy.exc.InvalidRequestError:
            # Not persisted.
            pass
        except psycopg2.errors.ForeignKeyViolation:
            # Error with foreign keys
            # TODO: FIX!!
            pass
        else:
            session.commit()


def setup(bot):
    bot.add_cog(Installation(bot))
