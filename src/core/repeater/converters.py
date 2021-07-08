# -*- coding: utf-8 -*-
import re
from datetime import timedelta
from typing import Optional

import discord
from discord.ext import commands
from discord.utils import find

from core.db.models.infraction import Mute
from core.db.models.role import Permissions

from ..db.utils import get_user
from ..utils.download import download
from .filters import FilterError
from .filters import FILTERS
from core.db.models.stream import Stream
from core.db.models.user import User
from core.utils.ratelimit import RateLimit


class MutedError(ValueError):
    """When a user is muted"""

    def __init__(self, last_mute, *args, **kwargs) -> None:
        self.last_mute = last_mute
        super().__init__(*args, **kwargs)


class Discord:
    bot = None
    _filter_ratelimit = RateLimit(limit=5, per=60)

    @classmethod
    def init_bot(cls, bot: commands.Bot) -> None:
        cls.bot = bot

    @classmethod
    def prepare_username(cls, name: str, discriminator: str, emojis: str) -> str:
        """
        Make a username webhook ready (< 32 characters)

        Parameters
        ----------
        name : str
            The username
        discriminator : str
            The discriminator
        emojis : str
            The emojis to add after the username and discriminator

        Returns
        -------
        str
            The correct username
        """
        suffix = f"#{discriminator}"
        suffix += "".join(emojis)

        max_name_length = 32 - len(suffix)
        if len(name) > max_name_length:
            username = name[: max_name_length - 1] + "\u2026"
        else:
            username = name

        return username + suffix

    @classmethod
    def prepare_content(cls, content: str) -> str:
        """
        Handle all mentions in a message's content

        Parameters
        ----------
        content : str
            The content to check

        Returns
        -------
        str
            The new content with handled mentions
        """
        # Find pings that did work, and replace it with monospace text.
        content, ignore = cls._transform_mentions(content)

        # Find all pings that didn't work (for example, interserver ones)
        content = cls._find_mentions(content, ignore)

        return content

    @classmethod
    def _format_mentions(cls, user, content, match, name, discrim):
        dbuser = get_user(user.id)
        last_seen = dbuser.last_seen()

        if last_seen is not None:
            return content.replace(
                match,
                "<`@{0.name}#{0.discriminator}`:{0.id}={1}>".format(user, last_seen.id),
            )
        return content.replace(match, "`@{0}#{1}`".format(name, discrim), 1)

    @classmethod
    def _find_mentions(cls, content, ignore):
        """
        Find all pings that didn't work (for example, interserver ones)

        Parameters
        ----------
        content : str
            Message content
        ignore : list
            List of mentions to ignore

        Returns
        -------
        str
            Message content
        """
        for match, name, discrim in re.findall(
            r"(@(.+?)(?:\u2026)?#(\d{4})(?:#0000)?)", content
        ):
            if match in ignore:
                continue

            # Find user in cache
            user = find(
                lambda u, name=name, discrim=discrim: u.name.startswith(name)
                and u.discriminator == discrim,
                cls.bot.users,
            )

            if user is not None:
                content = cls._format_mentions(user, content, match, name, discrim)

        return content

    @classmethod
    def _transform_mentions(cls, content: str):
        """
        Find pings that did work, and replace it with monospace text.

        Parameters
        ----------
        content : str
            The message content

        Returns
        -------
        str, list
            The message content, and list of mentions to ignore
        """
        ignore = []
        for match, id_ in re.findall(r"(<@\!?(\d+?)>(?:#0000)?)", content):
            user = cls.bot.get_user(int(id_))
            if user is not None:
                ignore.append("@{0.name}#{0.discriminator}".format(user))
                content = content.replace(
                    match, "`@{0.name}#{0.discriminator}`".format(user), 1
                )
            else:
                ignore.append("@Unknown#????")
                content = content.replace(match, "`@Unknown#????`", 1)

        return content, ignore

    @classmethod
    async def transform(cls, message: discord.Message, stream: Stream) -> dict:
        """
        Turn a Discord message into an appropriate message for RabbitMQ. Also
        checks filters

        Parameters
        ----------
        message : discord.Message
            The message to transform
        stream : Stream
            The stream to send it to

        Returns
        -------
        dict
            The message body
        """
        user = User.create(message.author)

        await cls.check_filters(user, message, stream)

        params = {
            "username": cls.prepare_username(
                message.author.name, message.author.discriminator, user.emojis
            ),
            "avatar_url": str(message.author.avatar_url_as(format="png")),
            "content": cls.prepare_content(message.content),
            "files": [
                await cls.prepare_attachment(attachment)
                for attachment in message.attachments
            ],
            "reference": message.reference,
        }

        return params

    @classmethod
    async def check_filters(
        cls,
        user: User,
        message: discord.Message,
        stream: Stream,
        automute: Optional[bool] = True,
    ) -> bool:
        """
        Check filters for incoming message an raise an error if they fail

        Parameters
        ----------
        user : User
            The user that the message is sent by
        message : discord.Message
            The message
        stream : Stream
            The stream to send it to
        automute : bool, optional
            Whether to mute them automatically if they've infringed filter
            restrictions too many times recently, by default True

        Returns
        -------
        bool
            Whether the filters pass. This method only returns if there hasn't
            been a failure.

        Raises
        ------
        FilterError
            The user has failed a filter
        """
        try:
            if user.has_permissions(Permissions.MANAGE_MUTES):
                return True
        except Exception:
            pass

        suppressed_filters = stream.suppressed_filters()
        for filter_name, filter_func in FILTERS.items():
            if filter_name in suppressed_filters:
                continue

            res = await filter_func(user, message, cls.bot, stream)
            if not res:
                # This function will throw an error if needed
                cls._ratelimit(user, filter_name=filter_name, automute=automute)

                raise FilterError(
                    filter_name,
                    "filter {} failed for {} on {}".format(filter_name, user, message),
                )

        return True

    @classmethod
    async def passes_filters(cls, *args, **kwargs) -> bool:
        """
        Utility function that wraps :func:`Discord.check_filters` and returns a
        value, even if it fails. This also disabled automute (unless
        specifically re-enabled via `**kwargs`)

        Returns
        -------
        bool
            Whether the filters passed
        """
        try:
            automute = kwargs.pop("automute", False)
            await cls.check_filters(*args, **kwargs, automute=automute)
        except (FilterError, MutedError):
            return False

        return True

    @classmethod
    def _ratelimit(
        cls, user: User, filter_name: str = "UNKNOWN_FILTER", automute: bool = True
    ):
        """
        Handle filter rates, automatically muting if the user violates a filter
        too many times

        Parameters
        ----------
        user : User
            The user sending the message
        filter_name : str, optional
            The name of the filter, by default "UNKNOWN_FILTER"
        automute : bool, optional
            Whether to mute automatically, by default True

        Raises
        ------
        MutedError
            The user was muted
        """
        excess = cls._filter_ratelimit.enter(user.id)
        if excess > 0 and automute:
            try:
                limit = cls._filter_ratelimit.limit
                last_mute = Mute.create(
                    user,
                    user,
                    timedelta(minutes=5),
                    f"Violating filter restrictions ({limit+excess}/{limit})"
                    f" - `{filter_name}`",
                )
            except ValueError:
                # Already muted, just ignore it
                pass
            else:
                raise MutedError(last_mute)

    # Other converters
    @staticmethod
    async def prepare_attachment(attachment: discord.Attachment) -> dict:
        return {
            "name": attachment.filename,
            "url": attachment.url,
            "body": (await download(attachment.url)).decode("latin-1"),
        }

    @staticmethod
    def prepare_embed(embed: discord.Embed) -> dict:
        return embed.to_dict()
