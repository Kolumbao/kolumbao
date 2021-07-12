# -*- coding: utf-8 -*-
from typing import Optional, TypeVar
import discord as dsc
from discord.ext.commands.bot import Bot
from sqlalchemy.ext.declarative import declarative_base

from . import *

Base = declarative_base()

T = TypeVar('T')
class SharedAttributes:
    _bot: Bot = None
    @staticmethod
    def init_bot(bot: Bot):
        if bot:
            SharedAttributes._bot = bot
    
    @property
    def bot(self) -> Bot:
        if self._bot is None:
            raise ValueError("Bot not yet initialized")
        
        return self._bot

    @property
    def discord(self) -> dsc.abc.Snowflake:
        # Try to get from all getter functions. Ideally overriden
        if hasattr(self, 'discord_id'):
            _id = self.discord_id
            return self.bot.get_guild(_id) or self.bot.get_channel(_id) or self.bot.get_user(_id)
        
        raise TypeError("This database object is not discord affiliated")
    
    @classmethod
    def create(cls: T, source: dsc.abc.Snowflake, create_default: bool = True) -> Optional[T]:
        # Circular import avoiding
        from .. import query, session

        dbobject = query(cls).filter(cls.discord_id == source.id).first()
        if dbobject is None and create_default:
            dbobject = cls(discord_id=source.id)
            session.add(dbobject)
        
        return dbobject


# NOTE: These imports MUST come after Base's declaration, as they depend
# on Base's existence.

from .announcement import Announcement
from .guild import Guild
from .infraction import Warn, Mute, Ban
from .message import OriginMessage, ResultMessage
from .node import Node
from .snippet import Snippet
from .stream import Feature, Stream, stream_features
from .role import Role, Permission
from .user import User
from .blacklist import Blacklist
