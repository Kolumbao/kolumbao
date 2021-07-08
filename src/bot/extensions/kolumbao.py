# -*- coding: utf-8 -*-
import asyncio
from datetime import datetime
from datetime import timedelta
from typing import List

import aiohttp
import discord
from discord.errors import Forbidden
from discord.errors import HTTPException
from discord.errors import NotFound
from discord.ext import commands
from discord.raw_models import RawMessageUpdateEvent
from discord.raw_models import RawReactionActionEvent
from discord_components.component import Select, SelectOption
from discord_components.interaction import Interaction
from bot.interactions import selection
from core.db.models.role import Permissions

from core.db.models.user import User

from ..checks import has_permission
from ..response import bad
from ..response import raw_resp
from ..response import resp
from bot.errors import ItemNotFound
from bot.format import format_time
from bot.format import format_user
from core.db import query
from core.db import session
from core.db.models import Node
from core.db.models import OriginMessage
from core.db.models.message import ResultMessage
from core.db.models.stream import Stream
from core.db.utils import get_stream
from core.i18n.i18n import _
from core.logs.log import GlobalDiscordHandler
from core.repeater.converters import Discord
from core.repeater.converters import MutedError
from core.repeater.filters import FilterError


class Kolumbao(commands.Cog):
    __badge__ = "<:greyedout:861644856837013524>"
    max_retries = 5

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        Discord.init_bot(bot)
        self.bot.logger.info(f"Started with {query(Node).count()} nodes")
        self.delete_queue = asyncio.Queue()
        self.delete_task = self.bot.loop.create_task(self._delete())

    @staticmethod
    def _with_error(delays, err: bool = True):
        min_latency = min(delays)
        max_latency = max(delays)
        error = (max_latency - min_latency) / 2
        average_latency = min_latency + error
        mean_latency = sum(delays, timedelta(0)) / len(delays)

        r = f"{average_latency.total_seconds()*1000:.2f}"
        if err:
            r += f"±{error.total_seconds()*1000:.2f} (avg. {mean_latency.total_seconds()*1000:.2f})"

        return r

    @has_permission("CREATE_ANNOUNCEMENTS")
    @commands.command()
    async def announce(self, ctx: commands.Context, *, content: str):
        # Find stream...
        streams = query(Stream).all()
        streams.sort(key=lambda stream: stream.message_count, reverse=True)
        stream_to_announce_to = []

        values, interaction = await selection(self.bot, ctx, {
            "ALL": _("ANNOUNCE__ALL"),
            **{
                stream.name: stream.name
                for stream in streams[:22]
            }
        }, max_values=len(streams[:22]) + 1)

        if values is None:
            return
        
        if "ALL" in values:
            stream_to_announce_to = streams
        else:
            stream_to_announce_to = [
                stream for stream in streams
                if stream.name in values
            ]
        
        tasks = []
        for stream in stream_to_announce_to:
            tasks.append(self.bot.client.send_art(
                content, stream
            ))

        await interaction.respond(content=_("ANNOUNCE__DONE"), ephemeral=False)
        await asyncio.gather(*tasks)

    @commands.command()
    async def delay(self, ctx):
        """Get current delay stats"""
        messages = await self.bot.loop.run_in_executor(
            None,
            (
                query(OriginMessage)
                .filter(OriginMessage.sent_at > datetime.now() - timedelta(days=1))
                .order_by(OriginMessage.sent_at.desc())
                .limit(100)
                .all
            ),
        )

        max_tot, min_tot, avg_tot = [], [], []
        for message in messages:
            max_, min_, avg_ = await self.bot.loop.run_in_executor(None, message.delay)
            if max_ == timedelta(0):
                continue
            max_tot.append(max_)
            min_tot.append(min_)
            avg_tot.append(avg_)

        embed = raw_resp(ctx, _("DELAY_CONTENT"))

        embed.add_field(name="Minimum Delay (ms)", value=self._with_error(min_tot))

        embed.add_field(name="Maximum Delay (ms)", value=self._with_error(max_tot))

        embed.add_field(name="Average Delay (ms)", value=self._with_error(avg_tot))

        embed.add_field(name="Delay with Discord", value=self.bot.latency)

        await ctx.send(embed=embed)

    @has_permission("INSPECT_CHANNELS")
    @commands.command()
    async def inspect(self, ctx, stream_name: str, amount: int = 10):
        """Inspect a channel's last few messages"""
        stream = get_stream(stream_name)
        if stream is None:
            raise ItemNotFound(Stream)

        await ctx.send(f"Replaying last {amount} messages...")
        messages: List[OriginMessage] = (
            query(OriginMessage)
            .filter(OriginMessage.stream_id == stream.id)
            .order_by(OriginMessage.sent_at.desc())
            .limit(amount)
            .all()
        )

        body = ""
        for message in messages[::-1]:
            user = message.user.discord
            new = f"[{format_time(message.sent_at)}] {format_user(user)}: *{message.content}*\n"
            if len(body + new) > 2000:
                await ctx.send(body)
                body = ""
            body += new

        if body != "":
            await ctx.send(body)

    async def _handle_message(
        self, message: discord.Message, node: Node, edit: bool = False
    ):  # pylint: disable=too-many-branches
        try:
            params = await Discord.transform(
                message,
                node.stream,
            )
        except (FilterError, MutedError) as err:
            # Oops
            try:
                await message.add_reaction("<:messagenotsent:794585504884064305>")
            except (Forbidden, HTTPException, NotFound):
                pass

            session.commit()
            if isinstance(err, MutedError):
                await self.bot.get_cog("Moderation").log_infraction(err.last_mute)
                await bad(message.channel, _("ERROR_AUTO_MUTED"))

            return
        except Exception:
            self.bot.logger.exception("Error while handling message")
            return

        # Get and commit just in case it didn't exist
        user = User.create(message.author)
        session.commit()

        if edit:
            original = (
                query(OriginMessage)
                .filter(OriginMessage.message_id == message.id)
                .first()
            )
            original.content = message.content
            session.commit()
            await self.bot.client.update(params, origin=original, target=node.stream)
        else:
            original = OriginMessage(
                user_id=user.id,
                message_id=message.id,
                node_id=node.id,
                stream_id=node.stream_id,
                content=message.content,
            )

            session.add(original)
            session.commit()
            await self.bot.client.send(params, origin=original, target=node.stream)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: RawMessageUpdateEvent):
        """Handles the message editing, also follows same filter rules as sending messages

        Args:
            payload (RawMessageUpdateEvent): The payload
        """
        if payload.data.get("webhook_id", None) is not None or payload.data.get(
            "author", {"bot": True}
        ).get("bot", False):
            return

        # Find source message
        dmessage = await self.bot.loop.run_in_executor(
            None,
            (
                query(OriginMessage)
                .filter(OriginMessage.message_id == payload.message_id)
                .first
            ),
        )
        if dmessage is not None:
            channel: discord.TextChannel = self.bot.get_channel(
                dmessage.node.channel_id
            )
            if channel is None:
                return

            try:
                message = await channel.fetch_message(dmessage.message_id)
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                return
            else:
                await self._handle_message(message, dmessage.node, edit=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Handles messages to be sent across Kolumbao

        Args:
            message (discord.Message): The message received
        """
        if message.author.bot:
            return

        if message.content.startswith(("]", "#", "kb!")):
            return

        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return

        # For logging purposes
        GlobalDiscordHandler.set_current_ctx(ctx)

        node = await self.bot.loop.run_in_executor(
            None, query(Node).filter(Node.channel_id == message.channel.id).first
        )
        if node is not None and not node.disabled:
            await self._handle_message(message, node)

    @commands.Cog.listener()
    async def on_raw_reaction_add(  # noqa: MC0001
        self, payload: RawReactionActionEvent
    ):
        try:
            quoted_message = await self.bot.loop.run_in_executor(
                None,
                (
                    query(OriginMessage)
                    .filter(
                        (OriginMessage.message_id == payload.message_id)
                        | (
                            OriginMessage.result_messages.any(
                                ResultMessage.message_id == payload.message_id
                            )
                        )
                    )
                    .first
                ),
            )

            if quoted_message is None:
                return

            if payload.emoji.name in ["🗑️", "❌"]:
                await self._handle_delete_reaction(payload, quoted_message)
            elif payload.emoji.name in ["❓", "❔"]:
                await self._handle_query_reaction(payload, quoted_message)

        except Exception:
            self.bot.logger.exception("Error handling reaction")

    async def _delete(self):
        while True:
            message_id, channel_id = await self.delete_queue.get()
            channel = self.bot.get_channel(channel_id)
            success = False
            if channel is None:
                success = True

            retries = 0
            while not success or retries >= self.max_retries:
                retries += 1
                success = await self._try_delete(channel, message_id)

            self.delete_queue.task_done()

    async def _handle_query_reaction(
        self, payload: RawReactionActionEvent, quoted_message: OriginMessage
    ):
        user = quoted_message.user.discord_id
        channel = quoted_message.node.channel_id
        guild = quoted_message.node.guild.discord_id
        target = self.bot.get_channel(payload.channel_id)
        try:
            if real_user := self.bot.get_user(user):
                user = f"{real_user} ({user})"
            if real_channel := self.bot.get_channel(channel):
                channel = f"#{real_channel.name} ({channel})"
            if real_guild := self.bot.get_guild(guild):
                guild = f"{real_guild.name} ({guild})"
        except Exception:
            pass
        else:
            await resp(
                target,
                f"""
User: {user}
Channel: {channel}
Guild: {guild}
""",
                supplementary_text=f"<@{payload.user_id}>, {user} | {channel} | {guild}",
            )

    async def _handle_delete_reaction(
        self, payload: RawReactionActionEvent, quoted_message: OriginMessage
    ):
        # Does the user have the right to manage messages in this channel?
        # Checks staff status and general permissions.
        manage_messages = quoted_message.stream.has_permissions(
            User.create(discord.Object(payload.user_id)), Permissions.MANAGE_MESSAGES
        )
        if quoted_message.user.discord_id != payload.user_id and not manage_messages:
            return

        amount = 0
        for message in [quoted_message, *quoted_message.result_messages]:
            # Sometimes the node is None, likely because of it being an
            # artificial message
            if message.node is not None:
                await self.delete_queue.put((message.message_id, message.node.channel_id))
                amount += 1

        session.delete(quoted_message)
        session.commit()
        try:
            message = await self.bot.get_channel(payload.channel_id).fetch_message(
                payload.message_id
            )
            await message.add_reaction("⌛")
            if manage_messages:
                text = (
                    "<@{}> I queued {} messages for deletion. "
                    "{} 'messages' are in the queue"
                )
                await message.channel.send(
                    text.format(payload.user_id, amount, self.delete_queue.qsize())
                )
        except Exception:
            pass

    async def _try_delete(  # pylint: disable=too-many-branches
        self, channel: discord.TextChannel, message_id: int
    ):
        try:
            message = await channel.fetch_message(message_id)
            await message.delete()
        except (discord.Forbidden, discord.NotFound):
            return True
        except discord.HTTPException as exc:
            if exc.status == 429:
                resp = await exc.response.json()
                await asyncio.sleep(resp.get("retry_after", 5.0) * 1.1)
            else:
                return True
        except aiohttp.client_exceptions.ServerDisconnectedError:
            pass
        except Exception:
            self.bot.logger.exception("Unknown error deleting message")
            return True
        else:
            return True

        return False

    @commands.command()
    async def deletion(self, ctx):
        await ctx.send("{} in the queue".format(self.delete_queue.qsize()))


def setup(bot):
    bot.add_cog(Kolumbao(bot))
