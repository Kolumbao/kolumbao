# -*- coding: utf-8 -*-
from discord.ext import commands

from ..checks import has_permission
from ..errors import ItemNotFound
from ..response import bad
from ..response import good
from ..response import resp
from core.db import session
from core.db.models import Feature
from core.db.models import Stream
from core.i18n.i18n import _


class Features(commands.Cog):
    __badge__ = "<:featuredefault:786012935398621234>"
    __badge_success__ = "<:featuresuccess:786012934915489826>"
    __badge_fail__ = "<:featurefail:786012935575175178>"

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @has_permission("MANAGE_FEATURES")
    @commands.command("get-features")
    async def get_features(self, ctx, name: str):
        """Get all features available on a stream"""
        stream = Stream.create(name)
        if stream is None:
            raise ItemNotFound(Stream)

        if len(stream.features) == 0:
            return await bad(ctx, _("GET_FEATURES__NO_FEATURES"))

        features = ", ".join(f"**{feature}**" for feature in stream.features)
        suppressed_filters = ", ".join(
            f"**{filt}**" for filt in stream.suppressed_filters()
        )
        await resp(
            ctx,
            _(
                "GET_FEATURES__CONTENT",
                features=features,
                suppressed_filters=suppressed_filters,
            ),
        )

    @has_permission("MANAGE_FEATURES")
    @commands.command("add-feature")
    async def add_feature(self, ctx, stream_name: str, feature_name: str.upper):
        """Add a feature to a channel"""
        stream = Stream.create(stream_name)
        if stream is None:
            raise ItemNotFound(Stream)

        feature = Feature.create(feature_name)

        if feature in stream.feats:
            return await bad(ctx, _("ADD_FEATURE__ALREADY_ADDED"))

        stream.feats.append(feature)
        session.commit()

        await good(ctx, _("ADD_FEATURE__SUCCESS"))

    @has_permission("MANAGE_FEATURES")
    @commands.command("remove-feature")
    async def remove_feature(self, ctx, stream_name: str, feature_name: str.upper):
        """Remove a feature from a channel"""
        stream = Stream.create(stream_name)
        if stream is None:
            raise ItemNotFound(Stream)

        feature = Feature.create(feature_name, create_default=False)
        if feature is None or feature not in stream.feats:
            return await bad(ctx, _("REMOVE_FEATURE__NOT_ADDED"))

        stream.feats.remove(feature)
        session.commit()

        await good(ctx, _("REMOVE_FEATURE__SUCCESS"))


def setup(bot):
    bot.add_cog(Features(bot))
