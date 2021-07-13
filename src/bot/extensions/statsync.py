# -*- coding: utf-8 -*-
import asyncio
import datetime
import math
from functools import partial
from io import BytesIO
from itertools import accumulate
from itertools import islice
from operator import attrgetter
from os import getenv
from typing import List
from typing import Tuple
import discord

import matplotlib
import matplotlib.pyplot as plt
from attr import dataclass
from discord import File
from discord.ext import commands
from discord.ext import tasks
from sortedcontainers import SortedDict

from ..checks import has_permission
from core.db.database import query
from core.db.models import OriginMessage
from core.db.models import ResultMessage
from core.db.models import Stream


def trunc(text, length):
    if len(text) < length:
        return text

    return text[: length - 3] + "..."


def closest(sorted_dict, key):
    "Return closest key in `sorted_dict` to given `key`."
    assert len(sorted_dict) > 0
    keys = list(islice(sorted_dict.irange(minimum=key), 1))
    keys.extend(islice(sorted_dict.irange(maximum=key, reverse=True), 1))
    return min(keys, key=lambda k: abs(key - k))


@dataclass
class GraphOptions:
    plot_same: bool = False
    fn: callable = attrgetter("plot")
    xdatetime: bool = False
    ydatetime: bool = False
    yscale: str = "linear"
    xscale: str = "linear"
    scalex: int = 1
    scaley: int = 1


class StatSync(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.update_top.start()
        # self.update_status.start()

    def cog_unload(self):
        self.update_top.stop()
        # self.update_status.stop()

    @tasks.loop(seconds=60)
    async def update_top(self):
        await self._update_top_streams()
        await self._update_hot_streams()
        await self._update_message_stats()

    @tasks.loop(minutes=60)
    async def update_status(self):
        streams = await self.bot.loop.run_in_executor(None, query(Stream).count)
        messages = await self.bot.loop.run_in_executor(None, query(OriginMessage).count)

        await self.bot.change_presence(
            activity=discord.Activity(
                name=f"{streams} streams | {messages} messages",
                type=discord.ActivityType.watching,
            )
        )

    async def _update_hot_streams(self):
        if getenv("HOT_CHANNELS_STATS") is None:
            return

        streams = await self.bot.loop.run_in_executor(None, query(Stream).all)

        def filt(messages):
            def _filt(m):
                return m.sent_at > datetime.datetime.now() - datetime.timedelta(weeks=1)

            return list(filter(_filt, messages))

        await self.bot.loop.run_in_executor(
            None,
            partial(
                streams.sort,
                key=lambda stream: len(filt(stream.messages)),
                reverse=True,
            ),
        )

        channel_ids = list(map(int, getenv("HOT_CHANNELS_STATS").split(",")))

        for s, stream in enumerate(streams[: len(channel_ids)]):
            channel = self.bot.get_channel(channel_ids[s])
            if channel is not None:
                brief = (
                    stream.description.split("\n")[0]
                    if stream.description
                    else "No description"
                )
                await channel.edit(
                    name=trunc(
                        f"{stream.name};{len(filt(stream.messages))};{brief}",
                        100,
                    )
                )

    async def _update_top_streams(self):
        if getenv("TOP_CHANNELS_STATS") is None:
            return

        streams = await self.bot.loop.run_in_executor(None, query(Stream).all)

        await self.bot.loop.run_in_executor(
            None,
            partial(
                streams.sort, key=lambda stream: stream.message_count, reverse=True
            ),
        )

        channel_ids = list(map(int, getenv("TOP_CHANNELS_STATS").split(",")))

        for s, stream in enumerate(streams[: len(channel_ids)]):
            channel = self.bot.get_channel(channel_ids[s])
            if channel is not None:
                brief = (
                    stream.description.split("\n")[0]
                    if stream.description
                    else "No description"
                )
                await channel.edit(
                    name=trunc(
                        f"{stream.name};{len(stream.nodes)};{stream.message_count};{brief}",
                        100,
                    )
                )

    async def _update_message_stats(self):
        messages_stats = self.bot.get_channel(int(getenv("MESSAGES_STATS")))
        if messages_stats is not None:
            await messages_stats.edit(name=query(OriginMessage).count())

        sentmessages_stats = self.bot.get_channel(int(getenv("SENTMESSAGES_STATS")))
        if sentmessages_stats is not None:
            await sentmessages_stats.edit(name=query(ResultMessage).count())

    def _create_graph(self, *graphs, options: GraphOptions = GraphOptions()):
        cmap = matplotlib.colors.LinearSegmentedColormap.from_list(
            "", ["#e4572e", "#ffb20f", "#ffe548"]
        )

        if options.plot_same or len(graphs) == 1:
            fig, axs = plt.subplots()
            axs = [axs]
        else:
            fig, axs = plt.subplots(len(graphs))

        plt.xscale(options.xscale)
        plt.yscale(options.yscale)
        fig.set_size_inches(10.5 * options.scalex, 10.5 * options.scaley)
        for g, (xs, ys) in enumerate(graphs):
            idx = 0 if options.plot_same or len(graphs) == 1 else g
            options.fn(axs[idx])(xs, ys, color=cmap(g / len(graphs)))

        if options.xdatetime:
            plt.gcf().autofmt_xdate()
        if options.ydatetime:
            plt.gcf().autofmt_ydate()

        buffer = BytesIO()
        plt.savefig(buffer, format="png")
        buffer.seek(0)

        return File(buffer, "stats.png")

    @has_permission("VIEW_ADVANCED_STATS")
    @commands.command("avg-time-month")
    async def avg_time_month(self, ctx):
        async with ctx.typing():
            dts: List[Tuple[datetime.datetime]] = await self.bot.loop.run_in_executor(
                None,
                query(OriginMessage.sent_at).all
            )

            data = {}
            for k in range(1, 13):
                data[k] = {}
                for i in range(24):
                    for j in range(60):
                        data[k][i + math.floor(j / 60 * 10) / 10] = 0

            for dt in dts:
                idx = dt[0].hour + math.floor(dt[0].minute / 60 * 10) / 10
                data[dt[0].month][idx] += 1

            graphs = []
            for month in sorted(data.keys()):
                xs = list(sorted(data[month].keys()))
                # tot = sum(data[month].values())
                # if tot == 0:
                #     continue
                ys = [data[month][x] for x in xs]
                graphs.append((xs, ys))

        await ctx.send(file=self._create_graph(*graphs))

    @has_permission("VIEW_ADVANCED_STATS")
    @commands.command("avg-time-all")
    async def avg_time_all(self, ctx):
        async with ctx.typing():
            dts: List[Tuple[datetime.datetime]] = await self.bot.loop.run_in_executor(
                None,
                query(OriginMessage.sent_at).all
            )

            graphs = []
            data = {}
            for i in range(24):
                for j in range(60):
                    data[i + math.floor(j / 60 * 10) / 10] = 0

            for dt in dts:
                idx = dt[0].hour + math.floor(dt[0].minute / 60 * 10) / 10
                data[idx] += 1

            keys = sorted(data.keys())
            xs = list(keys)
            ys = [data[x] for x in xs]
            graphs.append((xs, ys))

        await ctx.send(file=self._create_graph(*graphs, options=GraphOptions(scalex=3)))

    @has_permission("VIEW_ADVANCED_STATS")
    @commands.command("delay-history")
    async def delay_history(self, ctx, days: float = 5):
        async with ctx.typing():
            messages: List[OriginMessage] = await self.bot.loop.run_in_executor(
                None,
                query(OriginMessage)
                .filter(
                    OriginMessage.sent_at
                    > datetime.datetime.now() - datetime.timedelta(days=days)
                )
                .order_by(OriginMessage.sent_at.desc())
                .all,
            )

            ids = [message.id for message in messages]
            result_messages = await self.bot.loop.run_in_executor(
                None, query(ResultMessage).filter(ResultMessage.origin_id.in_(ids)).all
            )

            def _get_delays(message):
                def _wrapped():
                    sent_ats = [
                        rm.sent_at.timestamp()
                        for rm in result_messages
                        if rm.origin_id == message.id
                    ]
                    r = (
                        [
                            (
                                message.sent_at,
                                sum(sent_ats) / len(sent_ats)
                                - message.sent_at.timestamp(),
                            )
                        ]
                        if len(sent_ats) > 0
                        else []
                    )
                    return r

                return _wrapped

            tasks = []
            for message in messages:
                tasks.append(
                    self.bot.loop.run_in_executor(
                        None,
                        _get_delays(message),
                    )
                )


            res = await asyncio.gather(*tasks)
            results = sum(res, [])

            xs, ys = await self.bot.loop.run_in_executor(None, lambda: zip(*results))
            await ctx.send(
                file=self._create_graph(
                    (xs, ys),
                    options=GraphOptions(
                        fn=attrgetter("scatter"), xdatetime=True, scalex=days
                    ),
                )
            )

    # @has_permission("VIEW_ADVANCED_STATS")
    @commands.command("amount-history")
    async def amount_history(self, ctx, days: float = 5):
        initial = datetime.datetime.now() - datetime.timedelta(days=days)
        async with ctx.typing():
            messages: List[OriginMessage] = await self.bot.loop.run_in_executor(
                None,
                query(OriginMessage)
                .filter(OriginMessage.sent_at > initial)
                .order_by(OriginMessage.sent_at.desc())
                .all,
            )

            def _make_graph(interval=datetime.timedelta(minutes=20)):
                start = initial
                end = initial + interval

                data = SortedDict()
                while end < datetime.datetime.now():
                    data[start] = 0
                    start = end
                    end = start + interval

                for message in messages:
                    key = closest(data, message.sent_at)
                    data[key] += 1

                return zip(*data.items()), (
                    data.keys(),
                    list(accumulate(data.values())),
                )

            graphs = await self.bot.loop.run_in_executor(None, _make_graph)

            await ctx.send(
                file=self._create_graph(
                    *graphs,
                    options=GraphOptions(
                        xdatetime=True,
                    ),
                )
            )


def setup(bot):
    bot.add_cog(StatSync(bot))
