# -*- coding: utf-8 -*-
import asyncio
from typing import Optional
from uuid import uuid4

import discord
from discord.errors import NotFound
from discord.ext import commands
from discord.ext.commands.converter import UserConverter
from discord.ext.commands.errors import UserNotFound
from discord_components.component import ActionRow, ButtonStyle
from discord_components.interaction import Interaction, InteractionType
from expiring_dict import ExpiringDict

from core.db.models.user import User

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
from discord_components import DiscordComponents, Button, Select, SelectOption


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

    def __init__(self, bot: commands.Bot):
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

    async def _wait_for_response(self, ctx) -> discord.Message:
        return await self.bot.wait_for(
            "message",
            check=lambda m: m.author == ctx.author and m.channel == ctx.channel,
        )

    @commands.command(aliases=["edit"])
    async def manage(self, ctx, *, stream_name: str):
        stream = Stream.create(stream_name)
        if stream is None:
            raise ItemNotFound(Stream)

        dbuser = User.create(ctx.author)
        if stream.user == dbuser or dbuser.has_permissions("MANAGE_STREAMS"):
            self.bot.logger.info("Now managing {}".format(stream.name))

            interaction = None
            await ctx.send(
                _("MANAGE__OPTIONS"),
                components=[
                    ActionRow(
                        Button(
                            emoji=self.bot.get_emoji(860880431170453534),
                            label=_("MANAGE__SETTINGS"),
                            custom_id="settings",
                        ),
                        Button(
                            emoji=self.bot.get_emoji(860880431050129459),
                            label=_("MANAGE__STAFF"),
                            custom_id="staff",
                        ),
                    )
                ],
                ephemeral=False,
            )

            try:
                interaction: Interaction = await self.bot.wait_for(
                    "button_click", check=lambda i: i.user == ctx.author, timeout=60
                )
            except asyncio.TimeoutError:
                return await self.handle_interaction_end(ctx, interaction)
            else:
                if interaction.component.custom_id == "settings":
                    return await self.manage_stream_settings(ctx, stream, interaction)
                elif interaction.component.custom_id == "staff":
                    return await self.manage_stream_staff(ctx, stream, interaction)
        else:
            await bad(ctx, _("MANAGE__NOT_OWNED"))

    async def handle_interaction_end(self, ctx: commands.Context, interaction: Interaction):
        if not interaction or interaction.responded:
            return await resp(ctx, _("MANAGE__CLOSED"))
        else:
            return await resp(interaction, _("MANAGE__CLOSED"))

    async def manage_stream_settings(
        self,
        ctx: commands.Context,
        stream: Stream,
        interaction: Interaction
    ):
        # If the stream has password, give option to reset it
        reset_password_options = []
        if stream.password is not None:
            reset_password_options.append(
                SelectOption(label=_("MANAGE__RESET_PASSWORD"), value="reset-password")
            )

        # Use buttons
        await interaction.respond(
            content=_("MANAGE__PICK_OPTION"),
            components=[
                Select(
                    placeholder=_("MANAGE__SELECT"),
                    options=[
                        SelectOption(label=_("MANAGE__NAME"), value="name"),
                        SelectOption(
                            label=_("MANAGE__DESCRIPTION"), value="description"
                        ),
                        SelectOption(label=_("MANAGE__RULES"), value="rules"),
                        SelectOption(label=_("MANAGE__LANG"), value="lang"),
                        SelectOption(label=_("MANAGE__PASSWORD"), value="password"),
                        *reset_password_options,
                        SelectOption(label=_("MANAGE__NSFW"), value="nsfw"),
                        SelectOption(label=_("MANAGE__DELETE"), value="delete"),
                        SelectOption(label=_("MANAGE__CLOSE"), value="close"),
                    ],
                )
            ],
            ephemeral=False
        )
        
        interaction = None
        try:
            interaction: Interaction = await self.bot.wait_for(
                "select_option", check=lambda i: i.user == ctx.author, timeout=60
            )

            value = interaction.component[0].value

            if value == "close":
                raise asyncio.TimeoutError()
        except asyncio.TimeoutError:
            return await self.handle_interaction_end(ctx, interaction)
        else:
            functions = {
                "name": self.name,
                "description": self.description,
                "rules": self.rules,
                "lang": self.lang,
                "password": self.password,
                "reset-password": self.reset_password,
                "nsfw": self.nsfw,
                "delete": self.delete,
            }

            f = functions.get(value)
            await f(ctx, stream, interaction)

    async def manage_stream_staff(
        self,
        ctx: commands.Context,
        stream: Stream,
        interaction: Interaction
    ):
        staff_options = [
            SelectOption(
                label=str(user.discord), value=str(user.discord.id)
            ) for user in stream.staff
            if user.discord is not None
        ]

        await interaction.respond(
            content=_("MANAGE__REMOVE_STAFF"),
            components=[
                Select(
                    placeholder=_("MANAGE__SELECT"),
                    options=[
                        SelectOption(
                            label=_("MANAGE__NEW_STAFF"), value="new"
                        ),
                        *staff_options,
                        SelectOption(label=_("MANAGE__CLOSE"), value="close"),
                    ],
                )
            ],
            ephemeral=False
        )

        interaction = None
        while True:
            try:
                interaction: Interaction = await self.bot.wait_for(
                    "select_option", check=lambda i: i.user == ctx.author, timeout=60
                )

                value = interaction.component[0].value

                if value == "close":
                    raise asyncio.TimeoutError()
                elif value == "new":
                    await self.new_staff(ctx, stream, interaction)
                else:
                    user = User.create(discord.Object(value), create_default=False)
                    if user:
                        stream.staff.remove(user)
                    
                    session.commit()
                    await interaction.respond(
                        content=_("MANAGE__STAFF_REMOVED", staff=str(user.discord)), ephemeral=False
                    )
            except asyncio.TimeoutError:
                return await self.handle_interaction_end(ctx, interaction)
            else:
                pass
    
    async def new_staff(
        self,
        ctx: commands.Context,
        stream: Stream,
        interaction: Interaction
    ):
        await interaction.respond(content=_("NEW_STAFF__MENTION"), ephemeral=False)

        message = await self._wait_for_response(ctx)
        try:
            user = await UserConverter().convert(ctx, message.content)
        except UserNotFound:
            await bad(ctx, _("NEW_STAFF__USER_NOT_FOUND"))
        else:
            dbuser = User.create(user)
            stream.staff.append(dbuser)
            session.commit()
            await good(ctx, _("NEW_STAFF__SUCCESS"))


    async def name(
        self, ctx: commands.Context, stream: Stream, interaction: Interaction
    ):
        await interaction.respond(content=_("NAME__ENTER"), ephemeral=False)

        message = await self._wait_for_response(ctx)
        if Stream.create(message.content) is not None:
            return await bad(ctx, _("NAME__TAKEN"))

        stream.name = message.content
        session.commit()

        await good(ctx, _("NAME__SET", value=message.content))
        self.bot.logger.info(
            "Set name to {} for {}".format(message.content, stream.name)
        )

    async def description(
        self, ctx: commands.Context, stream: Stream, interaction: Interaction
    ):
        await interaction.respond(content=_("DESCRIPTION__ENTER"), ephemeral=False)

        message = await self._wait_for_response(ctx)
        stream.description = message.content
        session.commit()

        await good(ctx, _("DESCRIPTION__SET", value=message.content))
        self.bot.logger.info(
            "Set description to {} for {}".format(message.content, stream.name)
        )

    async def lang(
        self, ctx: commands.Context, stream: Stream, interaction: Interaction
    ):
        await interaction.respond(content=_("LANG__ENTER"), ephemeral=False)

        message = await self._wait_for_response(ctx)
        locale = I18n.get_locale(message.content)
        if locale is None:
            return await bad(ctx, _("LANG__NOT_FOUND"))

        stream.language = locale
        session.commit()

        await good(ctx, _("LANG__SET", value=message.content))
        self.bot.logger.info(
            "Set lang to {} for {}".format(message.content, stream.name)
        )

    async def rules(
        self, ctx: commands.Context, stream: Stream, interaction: Interaction
    ):
        await interaction.respond(content=_("RULES__ENTER"), ephemeral=False)

        message = await self._wait_for_response(ctx)
        stream.rules = message.content
        session.commit()

        await good(ctx, _("RULES__SET", value=message.content))
        self.bot.logger.info(
            "Set rules to {} for {}".format(message.content, stream.name)
        )

    async def password(
        self, ctx: commands.Context, stream: Stream, interaction: Interaction
    ):
        await interaction.respond(content=_("PASSWORD__ENTER"), ephemeral=False)

        message = await self._wait_for_response(ctx)
        stream.set_password(message.content)
        session.commit()

        await good(ctx, _("PASSWORD_SET"))
        self.bot.logger.info(
            "Set password to {} for {}".format(stream.password, stream.name)
        )

    async def reset_password(
        self, ctx: commands.Context, stream: Stream, interaction: Interaction
    ):
        stream.set_password(None)
        session.commit()

        await good(interaction, _("PASSWORD_RESET"))
        self.bot.logger.info(
            "Set password to {} for {}".format(stream.password, stream.name)
        )

    async def nsfw(
        self, ctx: commands.Context, stream: Stream, interaction: Interaction
    ):
        await interaction.respond(
            content=_("NSFW__OPTIONS"),
            components=[
                Button(
                    emoji=self.bot.get_emoji(860846678944776212),
                    style=ButtonStyle.green,
                    label=_("NSFW__YES"),
                    custom_id="yes",
                ),
                Button(
                    emoji=self.bot.get_emoji(860846700360105984),
                    style=ButtonStyle.red,
                    label=_("NSFW__NO"),
                    custom_id="no",
                ),
            ],
            ephemeral=False,
        )

        interaction: Interaction = await self.bot.wait_for(
            "button_click", check=lambda i: i.user == ctx.author, timeout=60
        )
        if interaction.component.custom_id == "yes":
            stream.nsfw = True
        else:
            stream.nsfw = False

        session.commit()

        await good(interaction, _("NSFW__SET", value=stream.nsfw))
        self.bot.logger.info("Set nsfw to {} for {}".format(stream.nsfw, stream.name))

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

    async def delete(
        self, ctx: commands.Context, stream: Stream, interaction: Interaction
    ):
        code = uuid4().hex
        await interaction.respond(
            content=_("DELETE__ENTER_CODE", code=code), ephemeral=False
        )

        message = await self._wait_for_response(ctx)
        if message.content != code:
            return await bad(ctx, _("DELETE__CODE_INVALID"))

        session.delete(stream)
        session.commit()
        await good(ctx, _("DELETE__SUCCESS"))

        self.bot.logger.info("Deleted {}".format(stream.name))


def setup(bot):
    bot.add_cog(Channels(bot))
